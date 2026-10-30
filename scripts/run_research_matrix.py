"""Research-v3 staged, resumable coordinator. Only validated real runs receive receipts."""
import concurrent.futures as cf,datetime,fcntl,hashlib,json,os,shutil,subprocess,sys,time,traceback,threading
from pathlib import Path
PROJECT_ROOT=Path(__file__).resolve().parents[1]
os.environ['MPLCONFIGDIR']=str(PROJECT_ROOT/'environment/matplotlib')
os.environ['TMPDIR']=str(PROJECT_ROOT/'environment/tmp')+'/'
os.environ['PYTHONPYCACHEPREFIX']=str(PROJECT_ROOT/'environment/pycache')
sys.pycache_prefix=os.environ['PYTHONPYCACHEPREFIX']
from run_research_case import ROOT,run_one,dump
from validate_research_case import validate
from archive_system_run import archive,digest
sys.path.insert(0,str(ROOT/'scripts/research_v3'))
from attack_benchmark import run as benchmark,snapshots
from fixed_observation_cost import run as fixed_cost
from freeze import freeze
BATCH=ROOT/'runs/research_v31_primary'
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def atomic(path,value):
 tmp=path.with_name(path.name+'.tmp');dump(tmp,value);tmp.replace(path)
def key(p):return hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:20]
def worker(params,area,role):
 output=Path(area)/key(params);output.mkdir(parents=True,exist_ok=True);receipt=output/'COMPLETE.json'
 if receipt.exists():
  result=json.loads(receipt.read_text());d=ROOT/result['directory'];cfg=json.loads((d/'run_config.json').read_text())
  assert cfg['params']==params and cfg['status']=='finished' and cfg['run_role']==role
  for name,sha in json.loads((d/'raw_file_sha256.json').read_text()).items():assert digest(d/name)==sha
  assert json.loads((d/'offline_validation.json').read_text())['status']=='passed'
  return result
 if shutil.disk_usage(ROOT).free<12*1024**3:raise RuntimeError('Under 12 GiB free: no new simulation started')
 d=run_one(params,output,role=role);report=validate(d)
 if not (d/'archive_manifest.json').exists():archive(d)
 validate(d)
 result={'task':key(params),'params':params,'directory':str(d.relative_to(ROOT)),'validation':report,'completed_utc':utc()};atomic(receipt,result);return result

def main():
 BATCH.mkdir(exist_ok=True);lock=(BATCH/'supervisor.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 started=time.time();design=json.loads((ROOT/'research_v3/design.json').read_text());rows=design['rows'];assert len(rows)==1190
 status_lock=threading.RLock();heartbeat_stop=threading.Event()
 status={'status':'running','stage':'gates','started_utc':utc(),'supervisor_pid':os.getpid(),'expected_primary_runs':len(rows),'primary_completed':0}
 def update(**kwargs):
  with status_lock:
   status.update(kwargs);status.update(updated_utc=utc(),elapsed_wall_s=time.time()-started,primary_completed=len(list((BATCH/'primary').glob('*/COMPLETE.json'))))
   atomic(BATCH/'status.json',status);atomic(ROOT/'PROJECT_STATUS.json',{'project':'Guarded Autonomy','remote_root':str(ROOT),**status})
 def heartbeat():
  while not heartbeat_stop.wait(30):update()
 threading.Thread(target=heartbeat,daemon=True).start()
 def execute(cases,area,role,workers,stage):
  cases=iter(cases);results=[];inflight={}
  with cf.ProcessPoolExecutor(max_workers=workers) as pool:
   def submit():
    try:p=next(cases)
    except StopIteration:return
    inflight[pool.submit(worker,p,str(area),role)]=p
   for _ in range(workers):submit()
   while inflight:
    done,_=cf.wait(inflight,timeout=30,return_when=cf.FIRST_COMPLETED);update(stage=stage,active_tasks=[key(p) for p in inflight.values()])
    for f in done:
     params=inflight.pop(f)
     try:r=f.result()
     except Exception as e:
      update(status='failed',failed_task=key(params),error=str(e))
      for q in inflight:q.cancel()
      raise
     results.append(r)
     with (BATCH/'events.jsonl').open('a') as out:out.write(json.dumps({'stage':stage,**r})+'\n')
     update(stage=stage,last_completed=r['task']);submit()
  return results
 try:
  update()
  for p in ['environment/research_v3_queue_regression_passed','environment/research_v3_python_gate_passed','runs/research_v31_integration_gates/DONE','runs/research_v3_full_development_periodic/DONE']:assert (ROOT/p).exists(),p
  dataset=[]
  for split,seeds in design['counterfactual_dataset_seeds'].items():
   dataset.extend({'experiment':'CF_dataset','configuration':'shielded_defer','model':'none','seed':s,'n':50,'vmax':20,'flows':10,'warmup_s':50,'sim_time_s':300,'drain_s':61,'adv_frac':.2,'attack':'T4','mobility':'steady_state_rwp','timing':'zero','initial_energy_j':1000.,'decision_cooldown_s':5,'capture_full_oracle':True,'split':split,'payload_file':str(ROOT/f'research_v3/payloads/{split}.json'),'proactive':True,'reciprocal_probe':True} for s in seeds)
  captured=json.loads((ROOT/'runs/research_v3_primary_periodic/dataset_receipts.json').read_text())
  assert {key(p) for p in dataset}=={key(x['params']) for x in captured}
  for rec in captured:
   d=ROOT/rec['directory']
   for name,sha in json.loads((d/'raw_file_sha256.json').read_text()).items():assert digest(d/name)==sha

  dump(BATCH/'dataset_receipts.json',captured)
  # The heldout states are collected mechanically; no heldout model response is queried
  # or scored until selection and the input manifest are frozen.
  update(stage='development_attack_selection',active_tasks=[])
  benchmark('development',[r for r in captured if r['params']['split']=='development'])
  snapshots([r for r in captured if r['params']['split']=='heldout'],'heldout')
  freeze()
  planning=[]
  for seed in design['evaluation_seeds']:
   base=next(p for p in rows if p['experiment']=='R1_utility' and p['scenario_id']=='link_cut' and p['seed']==seed and p['configuration']=='aodv')
   planning.append({**base,'experiment':'R1_failure_planning','induced_failures':False})
  plans=execute(planning,BATCH/'planning','planning',6,'failure_planning');mapping={}
  for r in plans:
   plan=json.loads((ROOT/r['directory']/'failure_plan.json').read_text());assert plan['available'] and plan['flows'],('no evaluable baseline link; halt rather than select another seed',r['params']['seed'])
   from guarded_autonomy.ns3.adapters import read_packets
   packets=read_packets(ROOT/r['directory'])
   recent={p.flow_id for p in packets if p.received_s is not None and plan['t']-5<=p.received_s<plan['t']}
   original=list(plan['flows']);plan={**plan,'flows':sorted(set(original)&recent)}
   assert plan['flows'],('selected baseline edge has no recently delivering cohort; halt without seed/edge substitution',r['params']['seed'])
   dump(Path(ROOT/r['directory']).parent/'failure_cohort_eligibility.json',{'window_s':5,'original_cohort':original,'recently_delivering_flows':sorted(recent),'selected_plan':plan})
   mapping[r['params']['seed']]=plan
  for row in rows:
   if row['experiment']=='R1_utility' and row['scenario_id']=='link_cut':
    plan=mapping[row['seed']];row.update(failure_from=plan['from'],failure_to=plan['to'],failure_flows=';'.join(map(str,plan['flows'])))
  expected=BATCH/'expected_matrix.json'
  if expected.exists():assert json.loads(expected.read_text())==rows
  else:dump(expected,rows)
  os.environ['GA_MODEL_PROFILE']='throughput'
  # R1 is completed first so evidence for the main scientific claim appears first.
  accepted=[]
  for exp in ['R1_utility','R2_ablation','R3_robustness','R5_injection_family','R0_probe_cost']:
   cases=[p for p in rows if p['experiment']==exp];cases.sort(key=lambda p:(p['seed'],p['scenario_id'],p['configuration'],p['model']))
   accepted.extend(execute(cases,BATCH/'primary','primary',6,exp))
   if exp=='R1_utility':
    dump(BATCH/'r1_accepted_runs.json',accepted)
    subprocess.run([sys.executable,str(ROOT/'scripts/report_research_r1.py')],check=True,cwd=ROOT)
  update(stage='heldout_attack_benchmark',active_tasks=[])
  benchmark('heldout',[r for r in captured if r['params']['split']=='heldout'])
  # No other experiment submits GPU work during these single-slot timing runs.
  os.environ['GA_MODEL_PROFILE']='single_slot'
  update(stage='fixed_observation_exclusive_cost',active_tasks=[])
  fixed_cost()
  accepted.extend(execute([p for p in rows if p['experiment']=='R4_cost'],BATCH/'primary','primary',1,'R4_exclusive_cost'))
  assert len(accepted)==len(rows) and {key(r['params']) for r in accepted}=={key(p) for p in rows}
  dump(BATCH/'accepted_runs.json',accepted);update(stage='final_analysis',active_tasks=[])
  subprocess.run([sys.executable,str(ROOT/'scripts/analyse_research_matrix.py')],check=True,cwd=ROOT)
  (BATCH/'DONE').write_text(utc()+'\n');update(status='finished',stage='complete')
 except BaseException as e:
  update(status='failed',error=f'{type(e).__name__}: {e}',traceback=traceback.format_exc());raise
 finally:heartbeat_stop.set()
if __name__=='__main__':main()
