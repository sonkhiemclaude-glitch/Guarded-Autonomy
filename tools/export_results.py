"""Export verified numerical summaries; exclude raw responses, narratives and manuscripts."""
from pathlib import Path
import argparse,csv,hashlib,io,json
ROOT=Path(__file__).resolve().parents[1]
ALLOWED={'condition_summary.csv','primary_paired_tests.csv','secondary_paired_tests.csv','heldout_attack_summary.csv','fixed_observation_cost_summary.csv','coverage.json'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def sanitise_csv(source):
 rows=list(csv.DictReader(io.StringIO(source)));fields=list(rows[0]) if rows else next(csv.reader(io.StringIO(source)));prefixes=set()
 for row in rows:
  candidates=[row.get('payload_file')]
  try:candidates.append(json.loads(row.get('condition','{}')).get('payload_file'))
  except (ValueError,AttributeError):pass
  for value in candidates:
   if value and '/research_v3/payloads/' in value and Path(value).is_absolute():prefixes.add(value.split('/research_v3/payloads/',1)[0])
 out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=fields,lineterminator='\n');writer.writeheader()
 for row in rows:
  clean={k:v for k,v in row.items()}
  for key,value in clean.items():
   for prefix in prefixes:value=value.replace(prefix,'${PROJECT_ROOT}')
   clean[key]=value
  writer.writerow(clean)
 return out.getvalue().encode(),len(prefixes)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--analysis',type=Path,required=True);p.add_argument('--output',type=Path,default=ROOT/'results/research-v31');a=p.parse_args();coverage=json.loads((a.analysis/'coverage.json').read_text())
 if not (coverage.get('complete') is True and coverage.get('expected')==coverage.get('accepted')==1190 and not coverage.get('synthetic',False)):
  raise SystemExit('Only complete real 1190-case analyses can be released')
 if coverage.get('analysis_code_sha256')!=sha(ROOT/'scripts/analyse_research_matrix.py'):
  raise SystemExit('Analysis implementation differs; investigate before release')
 hashes=json.loads((a.analysis/'artifact_sha256.json').read_text());prepared=[]
 for name,expected in hashes.items():
  path=Path(name)
  if path.is_absolute() or '..' in path.parts:raise SystemExit('Unsafe analysis manifest path')
  source=a.analysis/path
  if sha(source)!=expected:raise SystemExit('Analysis checksum mismatch: '+name)
  if name in ALLOWED:
   data,changed=sanitise_csv(source.read_text()) if path.suffix=='.csv' else (source.read_bytes(),0);prepared.append((path,data,expected,changed))
 if not ALLOWED <= {str(p) for p,data,old,n in prepared}:raise SystemExit('Required numerical summaries are missing; nothing exported')
 if a.output.exists() and any(a.output.iterdir()):raise SystemExit('Output directory is not empty; choose a new version to preserve earlier releases')
 a.output.mkdir(parents=True,exist_ok=True);manifest={}
 for name,data,original,changed in prepared:
  dest=a.output/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);manifest[str(name)]={'source_sha256':original,'released_sha256':hashlib.sha256(data).hexdigest(),'metadata_root_prefixes_replaced':changed}
 (a.output/'release_manifest.json').write_text(json.dumps({'scope':'Verified numerical summaries only. Absolute project-root metadata is replaced by ${PROJECT_ROOT}; numerical fields are unchanged. No raw model responses, narrative reports or manuscript files.','source_analysis_manifest_sha256':sha(a.analysis/'artifact_sha256.json'),'coverage':coverage,'files':manifest},indent=2)+'\n');print('Exported',len(prepared),'verified numerical files to',a.output)
if __name__=='__main__':main()
