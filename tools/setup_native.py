"""Fetch the pinned ns-3 release, apply source overlay and build the native scenario."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,sys,tarfile,urllib.request
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as stream:
  for b in iter(lambda:stream.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 (ROOT/'environment').mkdir(parents=True,exist_ok=True)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-archive',type=Path,help='Use an already downloaded ns-3.46.1.tar.bz2; checksum must match.');p.add_argument('--jobs',type=int,default=4);p.add_argument('--no-build',action='store_true');args=p.parse_args();assert 1<=args.jobs<=32
 data=json.loads((ROOT/'artifact_inputs/dependencies.json').read_text())['ns3'];downloads=ROOT/'vendor/downloads';downloads.mkdir(parents=True,exist_ok=True);archive=downloads/'ns-3.46.1.tar.bz2'
 if args.source_archive:
  if args.source_archive.resolve()!=archive.resolve():shutil.copy2(args.source_archive,archive)
 elif not archive.exists():
  temporary=archive.with_suffix('.part')
  with urllib.request.urlopen(data['url'],timeout=120) as response,temporary.open('wb') as out:shutil.copyfileobj(response,out)
  temporary.replace(archive)
 if sha(archive)!=data['sha256']:raise SystemExit('ns-3 archive checksum mismatch; nothing extracted')
 native=ROOT/'vendor/ns-3.46.1'
 if not native.exists():
  with tarfile.open(archive,'r:bz2') as tar:
   for m in tar.getmembers():
    name=Path(m.name)
    if name.is_absolute() or '..' in name.parts:raise SystemExit('Unsafe archive member')
   tar.extractall(ROOT/'vendor')
 for source in (ROOT/'native_overlay').rglob('*'):
  if source.is_file():
   dest=native/source.relative_to(ROOT/'native_overlay');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
 if args.no_build:print('Verified ns-3 source and overlay prepared.');return
 subprocess.run([sys.executable,'ns3','configure','--build-profile=optimized','--enable-modules=aodv,olsr,wifi,mobility,energy,applications,flow-monitor,buildings','--disable-examples','--disable-tests'],cwd=native,check=True)
 subprocess.run([sys.executable,'ns3','build','guarded-autonomy-manet','-j',str(args.jobs)],cwd=native,check=True)
 binary=native/'build/scratch/ns3.46.1-guarded-autonomy-manet-optimized';assert binary.is_file()
 (ROOT/'environment/native_build.json').write_text(json.dumps({'release':'3.46.1','archive_sha256':data['sha256'],'binary_sha256':sha(binary),'binary':str(binary.relative_to(ROOT))},indent=2)+'\n');print('Native scenario built:',binary)
if __name__=='__main__':main()
