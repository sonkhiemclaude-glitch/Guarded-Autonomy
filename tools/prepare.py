"""Materialise portable inputs. This command starts no simulations or model servers."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]

def main():
 for name in ['environment/tmp','environment/matplotlib','logs/model_servers','runs','research_v3/fixed_observation_cost']:(ROOT/name).mkdir(parents=True,exist_ok=True)
 src=ROOT/'artifact_inputs'
 for folder in ['research_v3','runs']:
  for p in (src/folder).rglob('*.json'):
   target=ROOT/p.relative_to(src);target.parent.mkdir(parents=True,exist_ok=True)
   text=p.read_text().replace('${PROJECT_ROOT}',str(ROOT))
   if not target.exists():target.write_text(text)
 models=json.loads((src/'models_manifest.template.json').read_text())
 for model in models.values():
  model['model_path']=str(ROOT/model['model_path'])
  for item in model['files']:item['path']=str(ROOT/item['path'])
 target=ROOT/'environment/models_manifest.json'
 if not target.exists():target.write_text(json.dumps(models,indent=2)+'\n')
 commit=ROOT/'environment/llama_cpp_commit.txt'
 if not commit.exists():commit.write_text('not-built; no inference runtime used by native smoke\n')
 print('Inputs prepared. No model weights downloaded; no inference or simulation started.')
if __name__=='__main__':main()
