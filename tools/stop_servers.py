"""Stop only model processes whose command line belongs to this artifact checkout."""
from pathlib import Path
import json,os,signal,subprocess
ROOT=Path(__file__).resolve().parents[1]
for name in ['model_servers','throughput_servers']:
 path=ROOT/f'environment/{name}.json'
 if not path.exists():continue
 for alias,record in json.loads(path.read_text()).items():
  pid=int(record['pid']);r=subprocess.run(['/bin/ps','-p',str(pid),'-o','command='],capture_output=True,text=True);command=r.stdout.strip()
  if not command:continue
  if str(ROOT/'vendor/llama.cpp/build/bin/llama-server') not in command or '--alias '+alias not in command:raise SystemExit(f'Refusing PID {pid}: process is not this checkout\'s {alias} server')
  os.kill(pid,signal.SIGTERM);print('Stopped',alias,pid)
 path.unlink()
