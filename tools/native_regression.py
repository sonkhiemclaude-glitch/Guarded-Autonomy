"""Build and run the retained-key/commit-hook regression against this checkout's libraries."""
from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def main():
 native=ROOT/'vendor/ns-3.46.1';lib=native/'build/lib';out=ROOT/'runs/native_api_regression';out.mkdir(parents=True,exist_ok=True);exe=out/'a1_a4_regression'
 subprocess.run(['clang++','-std=c++20','-I',str(native/'build/include'),str(ROOT/'native_tests/a1_a4_regression.cc'),'-L',str(lib),'-lns3.46.1-aodv-optimized','-lns3.46.1-internet-optimized','-lns3.46.1-network-optimized','-lns3.46.1-core-optimized','-Wl,-rpath,'+str(lib),'-o',str(exe)],check=True)
 r=subprocess.run([str(exe)],capture_output=True,text=True);(out/'results.jsonl').write_text(r.stdout);print(r.stdout,end='');r.check_returncode();report=json.loads(r.stdout.splitlines()[-1]);assert report['passed']==11 and report['failed']==0
if __name__=='__main__':main()
