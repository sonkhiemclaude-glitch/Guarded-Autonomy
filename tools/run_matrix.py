"""Run a new 1190-case replication using released fixed inputs; explicit opt-in required."""
from pathlib import Path
import argparse,collections,concurrent.futures,datetime,fcntl,hashlib,json,os,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'implementation/src'),str(ROOT/'scripts/research_v3')]
os.environ['MPLCONFIGDIR']=str(ROOT/'environment/matplotlib');os.environ['TMPDIR']=str(ROOT/'environment/tmp')+'/'
BATCH=ROOT/'runs/research_v31_primary'
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,obj):
 q=p.with_suffix(p.suffix+'.tmp');q.write_text(json.dumps(obj,indent=2)+'\n');q.replace(p)
def freeze():
 from guarded_autonomy.utils.provenance import package_fingerprint
 target=ROOT/'environment/research_v31_frozen_inputs.json'
 if target.exists():return json.loads(target.read_text())
 spec=json.loads((ROOT/'artifact_inputs/dependencies.json').read_text());actual=(ROOT/'environment/llama_cpp_commit.txt').read_text().strip()
 if actual!=spec['llama_cpp']['commit']:raise SystemExit('Build the pinned llama-server first.')
 models=json.loads((ROOT/'environment/models_manifest.json').read_text());registry=json.loads((ROOT/'environment/model_servers.json').read_text())
 if set(registry)!=set(models):raise SystemExit('Start all six single-slot servers first.')
 stats={}
 for name,model in models.items():
  for item in model['files']:
   p=Path(item['path']);assert p.stat().st_size==item['bytes'] and digest(p)==item['sha256'],p;st=p.stat();stats[str(p.relative_to(ROOT))]=[st.st_size,st.st_mtime_ns]
  with urllib.request.urlopen(f'http://127.0.0.1:{registry[name]["port"]}/health',timeout=3) as response:assert json.load(response)['status']=='ok'
 runtime=[ROOT/'vendor/ns-3.46.1/build/scratch/ns3.46.1-guarded-autonomy-manet-optimized',*sorted((ROOT/'vendor/ns-3.46.1/build/lib').glob('*.dylib')),ROOT/'vendor/llama.cpp/build/bin/llama-server']
 runtime += [p for p in (ROOT/'vendor/llama.cpp/build').rglob('*') if p.is_file() and p.suffix in ['.dylib','.metallib']]
 files=[p for folder in ['implementation/src','scripts','tools','native_overlay','artifact_inputs'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.py','.cc','.h','.hpp','.json','.txt','.yaml','.yml'] and '__pycache__' not in p.parts]
 files += [BATCH/'expected_matrix.json',ROOT/'environment/models_manifest.json']
 files += [ROOT/name for name in ['research_v3/design.json','research_v3/payloads/development.json','research_v3/payloads/heldout.json','research_v3/attack_benchmark/development_snapshots.json','research_v3/attack_benchmark/heldout_snapshots.json','research_v3/attack_benchmark/selected_development_attacks.json']]
 for name in ['model_servers','throughput_servers']:
  p=ROOT/f'environment/{name}.json'
  if not p.exists():save(p,{})
 serving={name:{model:{k:v for k,v in item.items() if k in ['argv','port','context_per_slot','slots']} for model,item in json.loads((ROOT/f'environment/{name}.json').read_text()).items()} for name in ['model_servers','throughput_servers']}
 record={'frozen_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'python_files':package_fingerprint(),'model_file_stats':stats,'model_files_verified':True,'source_files':{str(p.relative_to(ROOT)):digest(p) for p in files},'runtime_files':{str(p.relative_to(ROOT)):digest(p) for p in runtime},'serving_arguments':serving,'llama_cpp_commit':actual,'scope':'New replication campaign using released fixed states, selected wording and fixed baseline intervention plan; not the original execution or original development search.','reference_frozen_manifest_sha256':'25bddc5014bbdaa642376b7412337f53102ba2624c20c670def194e90000dee9'};save(target,record);return record
def execute(cases,workers):
 from run_research_matrix import worker
 area=BATCH/'primary';area.mkdir(exist_ok=True);pending={};results=[];iterator=iter(cases)
 with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
  def submit():
   try:params=next(iterator)
   except StopIteration:return
   pending[pool.submit(worker,params,str(area),'primary')]=params
  for _ in range(workers):submit()
  while pending:
   done,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
   for future in done:
    pending.pop(future)
    try:row=future.result()
    except BaseException:
     for waiting in pending:waiting.cancel()
     raise
    results.append(row);print('Accepted',row['params']['experiment'],row['task'],flush=True);submit()
 return results

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--confirm-long-run',action='store_true');p.add_argument('--workers',type=int,default=1);p.add_argument('--plan-only',action='store_true');a=p.parse_args();assert 1<=a.workers<=6
 path=BATCH/'expected_matrix.json'
 if not path.exists():raise SystemExit('Run python tools/prepare.py first.')
 rows=json.loads(path.read_text());assert len(rows)==len({json.dumps(p,sort_keys=True) for p in rows})==1190
 print(json.dumps(dict(collections.Counter(r['experiment'] for r in rows)),indent=2))
 if a.plan_only:return
 if not a.confirm_long_run:raise SystemExit('No cases started. This is a long, storage-intensive experiment; pass --confirm-long-run explicitly.')
 lock=(BATCH/'artifact_replication.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);freeze()
 accepted=[];profile=ROOT/'environment/throughput_servers.json';os.environ['GA_MODEL_PROFILE']='throughput' if profile.exists() and json.loads(profile.read_text()) else 'single_slot'
 for exp in ['R1_utility','R2_ablation','R3_robustness','R5_injection_family','R0_probe_cost']:
  cases=sorted([r for r in rows if r['experiment']==exp],key=lambda r:(r['seed'],r['scenario_id'],r['configuration'],r['model']));accepted.extend(execute(cases,a.workers))
 from attack_benchmark import run as benchmark
 benchmark('heldout',[])
 from fixed_observation_cost import run as fixed_cost
 fixed_cost();os.environ['GA_MODEL_PROFILE']='single_slot';accepted.extend(execute([r for r in rows if r['experiment']=='R4_cost'],1));assert len(accepted)==1190;save(BATCH/'accepted_runs.json',accepted)
 import analyse_research_matrix
 analyse_research_matrix.main();(BATCH/'DONE').write_text(datetime.datetime.now(datetime.timezone.utc).isoformat()+'\n');print('Replication and full analysis complete.',flush=True)
if __name__=='__main__':main()
