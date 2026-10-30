"""Serial resident-model cost on identical observations; separate from attack ASR."""
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from guarded_autonomy.agents.llm import LLMAgent,LLMEndpointConfig,http_json_transport
from run_research_case import dump,process_cpu_seconds
MODELS=['llama-3.2-1b','llama-3.2-3b','llama-3.1-8b','qwen2.5-1.5b','qwen2.5-3b','qwen2.5-7b']
def run():
 out=ROOT/'research_v3/fixed_observation_cost';out.mkdir(exist_ok=True)
 snaps=json.loads((ROOT/'research_v3/attack_benchmark/heldout_snapshots.json').read_text());assert len(snaps)==20
 registry=json.loads((ROOT/'environment/model_servers.json').read_text());path=out/'responses.jsonl'
 previous={r['case_id']:r for r in (json.loads(line) for line in path.read_text().splitlines())} if path.exists() else {}
 cases=[]
 for model in MODELS:
  for index in range(2):cases.append((model,snaps[0],'warmup',index))
 for index,snap in enumerate(snaps):
  order=sorted(MODELS,key=lambda m:hashlib.sha256((snap['snapshot_id']+m).encode()).hexdigest())
  cases.extend((model,snap,'measured',index) for model in order)
 with path.open('a') as stream:
  for model,snap,kind,index in cases:
   case_id=f'{kind}/{model}/{index}'
   if case_id in previous:continue
   usage={}
   def transport(url,payload,timeout):
    response=http_json_transport(url,payload,timeout);usage.update(response.get('usage',{}));return response
   agent=LLMAgent(LLMEndpointConfig(base_url=f'http://127.0.0.1:{registry[model]["port"]}',model=model,timeout_s=60.,extra={'seed':snap['seed']}),transport=transport)
   before=process_cpu_seconds(registry[model]['pid']);reply=agent.propose(snap['observation']);after=process_cpu_seconds(registry[model]['pid'])
   row={'case_id':case_id,'kind':kind,'model':model,'seed':snap['seed'],'snapshot_id':snap['snapshot_id'],'latency_ms':reply.latency_ms,'raw':reply.raw_text,'error':reply.error,'usage':usage,'model_server_cpu_s':after-before,'ambient_load_average':os.getloadavg(),'profile':'serial exclusive project inference, resident model, one slot'}
   stream.write(json.dumps(row,sort_keys=True)+'\n');stream.flush();previous[case_id]=row
 assert set(previous)=={f'{kind}/{model}/{index}' for model,snap,kind,index in cases} and len(previous)==132
 dump(out/'coverage.json',{'complete':True,'measured_real_calls':120,'warmup_real_calls':12,'response_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'input_snapshot_sha256':hashlib.sha256((ROOT/'research_v3/attack_benchmark/heldout_snapshots.json').read_bytes()).hexdigest(),'service_errors':sum(r['error'] is not None for r in previous.values())})
 print('FIXED OBSERVATION COST COMPLETE 120 measured + 12 warmup real queries',flush=True)
if __name__=='__main__':run()
