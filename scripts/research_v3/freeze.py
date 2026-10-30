import datetime,json,platform,sys,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from archive_system_run import digest
from guarded_autonomy.utils.provenance import package_fingerprint
from guarded_autonomy.agents.llm import SYSTEM_PROMPT
from run_research_case import dump,BINARY

def freeze():
 p=ROOT/'environment/research_v31_frozen_inputs.json'
 if p.exists():return json.loads(p.read_text())
 assert (ROOT/'environment/research_v3_queue_regression_passed').exists()
 assert (ROOT/'environment/research_v3_python_gate_passed').exists()
 assert (ROOT/'runs/research_v31_integration_gates/DONE').exists()
 assert (ROOT/'runs/research_v3_full_development_periodic/DONE').exists()
 assert (ROOT/'runs/research_v3_full_action_heuristic_gate/DONE').exists()
 assert (ROOT/'runs/research_v31_failure_gates/DONE').exists()
 assert (ROOT/'runs/component_check_research_v3_full_action/DONE').exists()
 endpoint=json.loads((ROOT/'environment/endpoint_validation_research_v3.json').read_text());assert len(endpoint['models'])==6 and all(x['valid']==50 for x in endpoint['models'].values())
 assert endpoint['prompt_sha256']==hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
 gate=json.loads((ROOT/'environment/research_v3_python_gate_passed').read_text());assert gate['python_files']==package_fingerprint()
 assert json.loads((ROOT/'research_v3/attack_benchmark/development_coverage.json').read_text())['complete']
 assert json.loads((ROOT/'research_v3/attack_benchmark/development_coverage.json').read_text())['errors']==0
 model_stats={}
 for model,record in json.loads((ROOT/'environment/models_manifest.json').read_text()).items():
  for item in record['files']:
   path=Path(item.get('path',item.get('local_path','')))
   if not path.is_file():
    hits=list((ROOT/'models').rglob(item.get('filename',item.get('name','__missing__'))));assert len(hits)==1,(model,item)
    path=hits[0]
   assert digest(path)==item['sha256'],path
   st=path.stat();model_stats[str(path.relative_to(ROOT))]=[st.st_size,st.st_mtime_ns]
 runtime=[BINARY,*sorted((ROOT/'vendor/ns-3.46.1/build/lib').glob('*.dylib'))]
 runtime += [ROOT/'vendor/llama.cpp/build/bin/llama-server']
 runtime += sorted(q for q in (ROOT/'vendor/llama.cpp/build').rglob('*') if q.is_file() and q.suffix in {'.dylib','.metallib'})
 source=[p for folder in ['scripts','implementation/ns3','vendor/ns-3.46.1/src/aodv/model'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in {'.py','.sh','.cc','.h'}]
 source += [ROOT/'research_v3/design.json',*sorted((ROOT/'research_v3').glob('*.md')),ROOT/'research_v3/attack_benchmark/selected_development_attacks.json',ROOT/'research_v3/attack_benchmark/development_snapshots.json',ROOT/'research_v3/attack_benchmark/heldout_snapshots.json',ROOT/'runs/research_v31_primary/dataset_receipts.json',ROOT/'environment/models_manifest.json',*sorted((ROOT/'research_v3/payloads').glob('*.json'))]
 record={'frozen_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':platform.node(),'python_files':package_fingerprint(),'runtime_files':{str(p.relative_to(ROOT)):digest(p) for p in runtime},'source_files':{str(p.relative_to(ROOT)):digest(p) for p in source},'model_file_stats':model_stats,'model_files_verified':True,'llama_cpp_commit':(ROOT/'environment/llama_cpp_commit.txt').read_text().strip()}
 archive=ROOT/'archive/research_v31_frozen';archive.mkdir(exist_ok=True)
 copies={str(q.relative_to(ROOT)):q for q in [*runtime,*source,*sorted((ROOT/'implementation/src/guarded_autonomy').rglob('*.py'))]}
 archived={}
 for relative,original in copies.items():
  target=archive/relative;target.parent.mkdir(parents=True,exist_ok=True);expected=digest(original)
  if target.exists():assert digest(target)==expected,('immutable archived input differs',relative)
  else:shutil.copy2(original,target)
  assert digest(target)==expected;archived[relative]=expected
 dump(archive/'archive_sha256.json',archived)
 record['frozen_archive']=str(archive.relative_to(ROOT));record['archived_files']=len(archived)
 record['serving_arguments']={name:{model:{k:v for k,v in entry.items() if k in ['argv','port','context_per_slot','slots']} for model,entry in json.loads((ROOT/f'environment/{name}.json').read_text()).items()} for name in ['model_servers','throughput_servers']}
 dump(p,record);shutil.copy2(p,archive/'frozen_inputs.json');print('RESEARCH V3 INPUTS FROZEN',len(source),'source files',len(archived),'archived files',flush=True);return record
