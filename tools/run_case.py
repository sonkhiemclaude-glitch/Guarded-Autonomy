"""Run one published plan cell in a new output directory; not the historical campaign."""
from pathlib import Path
import argparse,datetime,json,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'implementation/src')]
def main():
 p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--index',type=int);g.add_argument('--params',type=Path);g.add_argument('--list',action='store_true');a=p.parse_args();plan=ROOT/'runs/research_v31_primary/expected_matrix.json'
 if not plan.exists():raise SystemExit('Run python tools/prepare.py first.')
 rows=json.loads(plan.read_text())
 if a.list:
  for i,r in enumerate(rows):print(i,r['experiment'],r['scenario_id'],r['configuration'],r['model'],r['seed'],r.get('timing','zero'))
  return
 params=json.loads(a.params.read_text()) if a.params else rows[a.index]
 if params['model']!='none':
  registry=json.loads((ROOT/'environment/model_servers.json').read_text());record=registry[params['model']]
  with urllib.request.urlopen(f'http://127.0.0.1:{record["port"]}/health',timeout=3) as response:assert json.load(response)['status']=='ok'
 from run_research_case import run_one
 from validate_research_case import validate
 from archive_system_run import archive
 out=ROOT/'runs/artifact_cases'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');out.mkdir(parents=True)
 d=run_one(params,out,role='artifact_replication_case');report=validate(d);archive(d);validate(d);print(json.dumps({'directory':str(d.relative_to(ROOT)),'validation':report,'scope':'New replication case; not an original primary receipt.'},indent=2))
if __name__=='__main__':main()
