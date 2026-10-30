"""Run a short real ns-3 case with forced defer; no model or GPU inference is used."""
from pathlib import Path
import datetime,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'implementation/src')]
def main():
 if not (ROOT/'environment/models_manifest.json').exists():raise SystemExit('Run: python tools/prepare.py')
 from run_research_case import run_one
 from validate_research_case import validate
 from archive_system_run import archive
 params={'experiment':'artifact_native_smoke','configuration':'shielded_defer','model':'none','seed':100,'n':20,'vmax':5,'flows':3,'warmup_s':5,'sim_time_s':20,'drain_s':10,'adv_frac':0.,'attack':'none','mobility':'steady_state_rwp','timing':'zero','initial_energy_j':1000.,'decision_cooldown_s':5,'proactive':True,'reciprocal_probe':True}
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');out=ROOT/'runs/artifact_native_smoke'/stamp;out.mkdir(parents=True)
 d=run_one(params,out,role='artifact_smoke');result=validate(d);archive(d);validate(d)
 cfg=json.loads((d/'run_config.json').read_text());metrics=json.loads((d/'metrics.json').read_text());assert cfg['status']=='finished' and cfg['synthetic'] is False and metrics['llm_calls']==0;assert result['packet_rows']>0 and result['delivered_packets']>0
 report={'passed':True,'run_directory':str(d.relative_to(ROOT)),'real_ns3':True,'llm_calls':0,'packet_rows':result['packet_rows'],'delivered_packets':result['delivered_packets'],'scope':'Short integration smoke only; not a primary scientific result.'};(out/'SMOKE_COMPLETE.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
