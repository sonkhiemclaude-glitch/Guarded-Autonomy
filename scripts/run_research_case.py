"""Run real ns-3 pilots with a per-run bridge, immutable inputs and integrity checks."""
import platform,gzip,hashlib,json,os,resource,socketserver,subprocess,sys,threading,time
from pathlib import Path
from guarded_autonomy.agents.llm import SYSTEM_PROMPT
from guarded_autonomy.agents.policies import make_proposer,POLICY_VERSION
from guarded_autonomy.config import ShieldConfig
from guarded_autonomy.decision_log import HashChainLog
from guarded_autonomy.ns3.bridge import BridgeState,_Handler
from guarded_autonomy.ns3.settings import resolve_bridge
from guarded_autonomy.ns3.adapters import summarise_run
from guarded_autonomy.utils.provenance import run_metadata, package_fingerprint

ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/'vendor/ns-3.46.1/build/scratch/ns3.46.1-guarded-autonomy-manet-optimized'
MODELS=json.loads((ROOT/'environment/models_manifest.json').read_text())
BLOCK={'models':{k:{'base_url':f'http://127.0.0.1:{v["port"]}','model':k,'timeout_s':60,
                   'constraint':'json_schema','temperature':0.,'max_tokens':128} for k,v in MODELS.items()}}

def dump(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+'\n')


def process_cpu_seconds(pid):
    text=subprocess.check_output(['/bin/ps','-p',str(pid),'-o','time='],text=True).strip()
    parts=text.split(':')
    return sum(float(v)*60**i for i,v in enumerate(reversed(parts)))


def run_one(params,output,role='development'):
    if role == 'primary':
        frozen = json.loads((ROOT/'environment/research_v31_frozen_inputs.json').read_text())
        for relative, stat in frozen['model_file_stats'].items():
            current=(ROOT/relative).stat()
            if [current.st_size,current.st_mtime_ns] != stat:
                raise RuntimeError('frozen model file changed: '+relative)
        for relative, expected in {**frozen['runtime_files'],**frozen['source_files']}.items():
            if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError('frozen native/runtime input changed: '+relative)
        if frozen['python_files'] != package_fingerprint():
            raise RuntimeError('frozen Python source changed during primary matrix')
        for registry, expected in frozen['serving_arguments'].items():
            entries=json.loads((ROOT/f'environment/{registry}.json').read_text())
            current={model:{k:v for k,v in entry.items() if k in ['argv','port','context_per_slot','slots']} for model,entry in entries.items()}
            if current != expected:raise RuntimeError('frozen serving arguments changed: '+registry)
    block = json.loads(json.dumps(BLOCK))
    serving_profile = 'single_slot'
    if os.environ.get('GA_MODEL_PROFILE') == 'throughput' and params.get('timing', 'zero') == 'zero' and params.get('experiment') != 'R4_cost':
        throughput = json.loads((ROOT/'environment/throughput_servers.json').read_text())
        selected = throughput.get(params.get('model'))
        if selected:
            block['models'][params['model']]['base_url'] = f'http://127.0.0.1:{selected["port"]}'
            serving_profile = 'throughput_4_slots'
    bridge_cfg=resolve_bridge(block,params)
    if not bridge_cfg.get('agent'):
        serving_profile = 'local_policy' if bridge_cfg.get('proposer_kind') in {'defer','heuristic'} else 'no_agent'
    identity={'policy_version':POLICY_VERSION,'system_prompt_sha256':hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),'payload_sha256':hashlib.sha256(Path(params['payload_file']).read_bytes()).hexdigest() if params.get('payload_file') else None,'params':params,'effective_bridge':bridge_cfg,'scenario_sha256':hashlib.sha256(BINARY.read_bytes()).hexdigest(),
              'python_code_sha256':hashlib.sha256(json.dumps(package_fingerprint(),sort_keys=True).encode()).hexdigest(),
              'aodv_library_sha256':hashlib.sha256((ROOT/'vendor/ns-3.46.1/build/lib/libns3.46.1-aodv-optimized.dylib').read_bytes()).hexdigest()}
    run_id=params['experiment']+'-'+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    directory=output/run_id
    if directory.exists():
        current=json.loads((directory/'run_config.json').read_text())
        if current.get('status')=='finished':print('Already finished',run_id,flush=True);return directory
        raise FileExistsError('Use a fresh output directory for failed or unfinished runs: '+str(directory))
    directory.mkdir(parents=True)
    config={'run_id':run_id,'experiment':params['experiment'],'params':params,'synthetic':False,
            'effective_bridge':bridge_cfg,'status':'running','identity':identity,'run_role':role}
    dump(directory/'run_config.json',config)
    agent=make_proposer(bridge_cfg)
    stream=(directory/'decisions.jsonl').open('w')
    oracle_stream=gzip.open(directory/'oracle.jsonl.gz','wt',compresslevel=1)
    calls_stream=(directory/'agent_calls.jsonl').open('w')
    observations_stream=gzip.open(directory/'observations.jsonl.gz','wt',compresslevel=1)
    audit_stream=(directory/'daemon_audits.jsonl').open('w')
    state=BridgeState(ShieldConfig.from_mapping(bridge_cfg['shield']),agent=agent,agent_kind=bridge_cfg['proposer_kind'],
                      shielded=bridge_cfg['shielded'],sanitise_inputs=bridge_cfg['sanitise_inputs'],
                      run_dir=directory,decisions_out=stream,oracle_out=oracle_stream,agent_calls_out=calls_stream,observations_out=observations_stream,daemon_audit_out=audit_stream,capture_full_oracle=bool(params.get("capture_full_oracle",False)))
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address=True
        daemon_threads=True
    server=Server(('127.0.0.1',0),_Handler);server.state=state
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    port=server.server_address[1]
    command=[str(BINARY),f'--outDir={directory}',f'--bridgePort={port}']
    for key,value in sorted(params.items()):
        if key in {'temperature','scenario_id','split','capture_full_oracle','failure_available','payload_split','case_id'}:continue
        command.append(f'--{key}='+('true' if value is True else 'false' if value is False else str(value)))
    dump(directory/'command.json',command)
    metadata=run_metadata({'params':params,'effective_bridge':bridge_cfg},False,{'execution_host':platform.node(),
                          'ns3_release':'3.46.1','ns3_binary_sha256':identity['scenario_sha256'],
                          'model':MODELS.get(params.get('model')) if bridge_cfg.get('agent') else None,'serving_profile':serving_profile,
                          'scope':'primary real ns-3 system matrix' if role=='primary' else 'development validation only',
                          'run_role':role,'policy_version':POLICY_VERSION,'proposer_kind':bridge_cfg['proposer_kind'],'system_prompt_sha256':identity['system_prompt_sha256'],'ambient_load_average':os.getloadavg(),
                          'llama_cpp_commit':(ROOT/'environment/llama_cpp_commit.txt').read_text().strip()})
    dump(directory/'run_metadata.json',metadata)
    server_record = None
    registry = ROOT/'environment'/('throughput_servers.json' if serving_profile.startswith('throughput') else 'model_servers.json')
    if bridge_cfg.get('agent'):
        server_record = json.loads(registry.read_text()).get(params.get('model'))
    model_cpu_before = process_cpu_seconds(server_record['pid']) if server_record else None
    bridge_before = resource.getrusage(resource.RUSAGE_SELF)
    start=time.monotonic()
    try:
        if os.environ.get('GA_DEBUG_NATIVE'):
            command=['/usr/bin/lldb','--batch','-o','run','-o','thread backtrace all','--',*command]
        with (directory/'ns3.log').open('w') as log:
            process=subprocess.Popen(command,cwd=BINARY.parent,stdout=log,stderr=subprocess.STDOUT,
                                     env={**os.environ,'TMPDIR':str(ROOT/'environment/tmp')+'/'})
            killer=threading.Timer(86400,process.kill)
            killer.daemon=True
            killer.start()
            try:
                _,wait_status,child_usage=os.wait4(process.pid,0)
                process.returncode=os.waitstatus_to_exitcode(wait_status)
            finally:
                killer.cancel()
        if os.environ.get('GA_DEBUG_NATIVE'):raise RuntimeError('Debugger run only; inspect ns3.log')
        if process.returncode:raise RuntimeError(f'ns-3 exit {process.returncode}; see {directory}/ns3.log')
        stream.flush()
        scenario=json.loads((directory/'scenario_summary.json').read_text())
        assert scenario['completed'] and scenario['synthetic'] is False
        ns3_anchors=json.loads((directory/'ns3_anchors.json').read_text())
        for node,anchor in ns3_anchors.items():
            assert HashChainLog.load_jsonl(directory/f'chain-node-{node}.jsonl').verify(anchor['head']),node
        row=summarise_run(directory)
        if row['unknown_harm_proposals']:raise RuntimeError('unknown harm labels in pilot')
        dump(directory/'metrics.json',row)
        config['status']='finished'
        config['integrity']='all per-node chains match simulator-exported anchors'
        print('FINISHED',run_id,'PDR',row['pdr'],'calls',row['agent_calls'],'proposals',row['proposal_count'],flush=True)
    except Exception as error:
        config['status']='failed';config['error']=f'{type(error).__name__}: {error}'
        print('FAILED',run_id,config['error'],flush=True)
        raise
    finally:
        config['wall_s']=time.monotonic()-start
        if 'child_usage' in locals():
            config['ns3_cpu_s']=child_usage.ru_utime+child_usage.ru_stime
            config['ns3_peak_rss_bytes']=child_usage.ru_maxrss
        bridge_after=resource.getrusage(resource.RUSAGE_SELF)
        config['bridge_cpu_s']=bridge_after.ru_utime+bridge_after.ru_stime-bridge_before.ru_utime-bridge_before.ru_stime
        if server_record and model_cpu_before is not None:
            try:
                config['model_server_cpu_s']=process_cpu_seconds(server_record['pid'])-model_cpu_before
            except (subprocess.CalledProcessError, ValueError):
                config['model_server_cpu_s']=None
                config['model_cpu_measurement_error']='model server exited during run'
            config['model_server_cpu_scope']='exclusive per-run' if serving_profile=='single_slot' else 'shared server interval; not per-request CPU'
        config['serving_profile']=serving_profile
        dump(directory/'run_config.json',config)
        server.shutdown();server.server_close();thread.join(timeout=5);stream.close();oracle_stream.close();calls_stream.close();observations_stream.close();audit_stream.close();state.close_logs()
    return directory


if __name__=='__main__':
    output=ROOT/'runs'/sys.argv[1];output.mkdir(parents=True,exist_ok=True)
    cases=sys.argv[2:] or ['aodv','trust_aware_aodv','shielded']
    for config in cases:
        run_one({'experiment':'pilot','configuration':config,'model':'qwen2.5-1.5b','seed':0,'n':20,
                 'vmax':5,'flows':3,'warmup_s':5,'sim_time_s':20,'adv_frac':0.,'attack':'none',
                 'mobility':'steady_state_rwp','timing':'zero'},output)
