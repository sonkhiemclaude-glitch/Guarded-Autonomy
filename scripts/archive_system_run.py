"""Lossless archive with content and stored-byte digests; compatible with run readers."""
import gzip,hashlib,json,shutil
from pathlib import Path

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def archive(directory):
 manifest={}
 for p in sorted(directory.iterdir()):
  if p.is_file() and p.suffix in {'.csv','.jsonl','.xml'}:
   before=digest(p);target=p.with_name(p.name+'.gz')
   if target.exists():raise FileExistsError(target)
   temporary=target.with_name(target.name+'.tmp')
   with p.open('rb') as source,temporary.open('wb') as raw:
    with gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=1,mtime=0) as dest:shutil.copyfileobj(source,dest)
   h=hashlib.sha256()
   with gzip.open(temporary,'rb') as stream:
    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
   assert h.hexdigest()==before, 'archive mismatch'
   temporary.replace(target);p.unlink()
   manifest[p.name]={'uncompressed_sha256':before,'gzip_sha256':digest(target)}
 (directory/'archive_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 stored={p.name:digest(p) for p in sorted(directory.iterdir()) if p.is_file() and p.name!='raw_file_sha256.json'}
 (directory/'raw_file_sha256.json').write_text(json.dumps(stored,indent=2)+'\n')
 return manifest
