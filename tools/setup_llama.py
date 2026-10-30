"""Build the pinned llama-server. This command performs no model inference."""
from pathlib import Path
import argparse,json,subprocess
ROOT=Path(__file__).resolve().parents[1]
def main():
 (ROOT/'environment').mkdir(parents=True,exist_ok=True)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--jobs',type=int,default=4);a=p.parse_args();assert 1<=a.jobs<=32;spec=json.loads((ROOT/'artifact_inputs/dependencies.json').read_text())['llama_cpp'];source=ROOT/'vendor/llama.cpp'
 if not source.exists():
  subprocess.run(['git','clone','--filter=blob:none',spec['repository'],str(source)],check=True);subprocess.run(['git','-C',str(source),'checkout','--detach',spec['commit']],check=True)
 actual=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
 if actual!=spec['commit']:raise SystemExit('llama.cpp checkout differs from the pinned commit; not overwriting it.')
 if subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip():raise SystemExit('llama.cpp source has local modifications; preserve and investigate them first.')
 subprocess.run(['cmake','-S',str(source),'-B',str(source/'build'),'-DGGML_METAL=ON','-DLLAMA_CURL=OFF','-DCMAKE_BUILD_TYPE=Release'],check=True);subprocess.run(['cmake','--build',str(source/'build'),'--target','llama-server','-j',str(a.jobs)],check=True)
 (ROOT/'environment/llama_cpp_commit.txt').write_text(actual+'\n');print('Built pinned llama-server:',source/'build/bin/llama-server')
if __name__=='__main__':main()
