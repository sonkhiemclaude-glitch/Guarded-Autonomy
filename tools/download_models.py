"""Download selected pinned GGUF files and verify SHA-256; model terms remain upstream."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys,urllib.request,urllib.parse
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as stream:
  for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
 return h.hexdigest()
class SafeRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,request,fp,code,msg,headers,newurl):
  if urllib.parse.urlparse(newurl).scheme!='https':raise RuntimeError('Refusing non-HTTPS model redirect')
  redirected=super().redirect_request(request,fp,code,msg,headers,newurl)
  if redirected and urllib.parse.urlparse(newurl).hostname!=urllib.parse.urlparse(request.full_url).hostname:redirected.remove_header('Authorization')
  return redirected
def main():
 models=json.loads((ROOT/'artifact_inputs/models_manifest.template.json').read_text());p=argparse.ArgumentParser(description=__doc__);group=p.add_mutually_exclusive_group(required=True);group.add_argument('--model',choices=list(models));group.add_argument('--all',action='store_true');a=p.parse_args();selected=models if a.all else {a.model:models[a.model]}
 for name,model in selected.items():
  for item in model['files']:
   path=ROOT/item['path'];path.parent.mkdir(parents=True,exist_ok=True)
   if path.exists():
    if sha(path)==item['sha256']:print('Verified existing',path.name,flush=True);continue
    raise SystemExit(f'Existing model checksum mismatch: {path}; preserve and investigate it before retrying.')
   url=f'https://huggingface.co/{model["repository"]}/resolve/{model["revision"]}/{item["filename"]}';headers={}
   if os.environ.get('HF_TOKEN'):headers['Authorization']='Bearer '+os.environ['HF_TOKEN']
   temporary=path.with_suffix(path.suffix+'.partial');print('Downloading',name,item['filename'],flush=True)
   with urllib.request.build_opener(SafeRedirect()).open(urllib.request.Request(url,headers=headers),timeout=120) as response,temporary.open('wb') as out:shutil.copyfileobj(response,out,length=8*1024*1024)
   if temporary.stat().st_size!=item['bytes'] or sha(temporary)!=item['sha256']:raise SystemExit(f'Download checksum/size mismatch: {temporary}')
   temporary.replace(path);print('Verified',path.name,flush=True)
if __name__=='__main__':main()
