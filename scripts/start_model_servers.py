import json,os,socket,subprocess,time,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
server=root/'vendor/llama.cpp/build/bin/llama-server'
logdir=root/'logs/model_servers';logdir.mkdir(exist_ok=True)
started={}
for iteration in range(600):
    path=root/'environment/models_manifest.json'
    manifest=json.loads(path.read_text()) if path.exists() else {}
    for name,model in manifest.items():
        if name in started:continue
        with socket.socket() as sock:
            sock.settimeout(.2)
            if sock.connect_ex(('127.0.0.1',model['port']))==0:
                raise SystemExit(f'Refusing to replace existing listener on port {model["port"]}')
        command=[str(server),'--model',model['model_path'],'--alias',name,'--host','127.0.0.1',
                 '--port',str(model['port']),'--ctx-size','16384','--parallel','1','--n-gpu-layers','99',
                 '--threads','4','--jinja']
        with (logdir/(name+'.log')).open('w') as output:
            process=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                                     start_new_session=True,cwd=root,env={**os.environ,'TMPDIR':str(root/'environment/tmp')+'/'})
        started[name]={'pid':process.pid,'port':model['port'],'argv':command,'model':model}
        print('Started',name,'PID',process.pid,flush=True)
        (root/'environment/model_servers.json').write_text(json.dumps(started,indent=2)+'\n')
    if len(started)==6:break
    time.sleep(5)
else:raise SystemExit('Models were not fully provisioned within timeout')
for name,record in started.items():
    for _ in range(120):
        try:
            response=json.load(urllib.request.urlopen(f'http://127.0.0.1:{record["port"]}/health',timeout=2))
            if response.get('status')=='ok':break
        except Exception:pass
        time.sleep(2)
    else:raise SystemExit('Server failed health check: '+name)
    print('Healthy',name,flush=True)
(root/'environment/model_servers_ready').touch()
