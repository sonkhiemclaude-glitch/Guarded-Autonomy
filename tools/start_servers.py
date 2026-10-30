"""Start only requested artifact model servers on localhost; never replace listeners."""
from pathlib import Path
import argparse,json,os,socket,subprocess,time,urllib.request
ROOT=Path(__file__).resolve().parents[1]
def start(name,model,port,slots):
 binary=ROOT/'vendor/llama.cpp/build/bin/llama-server';path=Path(model['model_path'])
 if not binary.is_file() or not path.is_file():raise SystemExit('Missing model/server. Run setup_llama.py and download_models.py first.')
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',port))==0:raise SystemExit(f'Port {port} already has a listener; refusing to replace it.')
 args=[str(binary),'--model',str(path),'--alias',name,'--host','127.0.0.1','--port',str(port),'--ctx-size',str(16384*slots),'--parallel',str(slots),'--n-gpu-layers','99','--threads','4','--jinja']
 out=ROOT/'logs/model_servers'/f'{name}-{slots}slot.log';out.parent.mkdir(parents=True,exist_ok=True)
 with out.open('w') as log:p=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'TMPDIR':str(ROOT/'environment/tmp')+'/'})
 for _ in range(180):
  if p.poll() is not None:raise SystemExit(f'{name} exited; inspect {out}')
  try:
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as response:
    if json.load(response).get('status')=='ok':return {'pid':p.pid,'port':port,'argv':args,'slots':slots,'context_per_slot':16384,'model':model}
  except Exception:pass
  time.sleep(1)
 raise SystemExit(f'{name} did not become healthy; inspect {out}')
def main():
 manifest=json.loads((ROOT/'environment/models_manifest.json').read_text());p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--model',choices=list(manifest));g.add_argument('--all',action='store_true');p.add_argument('--throughput',action='store_true',help='Start the extra 4-slot 1B/8B endpoints for timing-zero batches.');a=p.parse_args()
 names=list(manifest) if a.all else [a.model]
 if a.throughput:
  names=[n for n in names if n in ['llama-3.2-1b','llama-3.1-8b']]
  if not names:raise SystemExit('Throughput endpoints apply only to Llama 1B/8B.')
 registry=ROOT/'environment'/('throughput_servers.json' if a.throughput else 'model_servers.json');records=json.loads(registry.read_text()) if registry.exists() else {}
 for name in names:
  port={'llama-3.2-1b':19101,'llama-3.1-8b':19102}[name] if a.throughput else manifest[name]['port'];records[name]=start(name,manifest[name],port,4 if a.throughput else 1);registry.write_text(json.dumps(records,indent=2)+'\n');print('Healthy',name,port,flush=True)
if __name__=='__main__':main()
