import json,os,socket,subprocess,time,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
models=json.loads((root/'environment/models_manifest.json').read_text())
records={}
for name,port in [('llama-3.2-1b',18101),('llama-3.1-8b',18102)]:
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',port))==0:raise SystemExit('port already in use')
    command=[str(root/'vendor/llama.cpp/build/bin/llama-server'),'--model',models[name]['model_path'],
             '--alias',name,'--host','127.0.0.1','--port',str(port),'--ctx-size','65536','--parallel','4',
             '--n-gpu-layers','99','--threads','4','--jinja']
    with (root/f'logs/model_servers/{name}-throughput.log').open('w') as output:
        p=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True,cwd=root)
    records[name]={'pid':p.pid,'port':port,'argv':command,'profile':'throughput, zero simulated latency only',
                   'context_per_slot':16384,'slots':4}
(root/'environment/throughput_servers.json').write_text(json.dumps(records,indent=2)+'\n')
for name,server in records.items():
    for _ in range(120):
        try:
            health=json.load(urllib.request.urlopen(f'http://127.0.0.1:{server["port"]}/health',timeout=3))
            if health.get('status')=='ok':break
        except Exception:pass
        time.sleep(2)
    else:raise SystemExit('server health failure '+name)
    print('Healthy',name,'4 slots, zero-latency batches only',flush=True)
(root/'environment/throughput_servers_ready').touch()
