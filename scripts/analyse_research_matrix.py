"""Strict final research tables: complete matrix membership, paired seeds, no pilot pooling."""
import csv,gzip,json,math,sys
from collections import defaultdict,Counter
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from guarded_autonomy.metrics.stats import t_interval,wilcoxon_signed_rank
from guarded_autonomy.ns3.adapters import summarise_run,read_packets,read_failures
from guarded_autonomy.schemas import parse_action,RouteChange,Isolate
from run_research_case import ROOT,dump
from archive_system_run import digest
from research_v3.network_asr import network_asr
BATCH=ROOT/'runs/research_v31_primary';OUT=BATCH/'analysis'
IGNORE={'seed','failure_from','failure_to','failure_flows'}
METRICS=['pdr','delay_p95_s','routing_overhead','recovery_rmst_s','recovery_recovered_fraction','recovery_pre_cut_live_fraction','recovery_post_cut_cohort_pdr','harmful_proposal_rate','residual_harm_rate','query_time_harmful_commits','query_time_commit_count','query_time_harmful_commit_fraction','review_pending_final','review_closed_final','review_overdue_final','query_time_fallback_harmful_commits','cache_false_neighbor_fraction','cache_missing_neighbor_fraction','agent_latency_ms_mean','shield_cpu_us_mean','shield_wall_us_mean','wall_s','ns3_cpu_s','bridge_cpu_s','model_server_cpu_s','llm_calls','agent_errors','invalid_replies','defer_replies','tier_share_agent','tier_share_base','tier_share_null']
METRICS += ['blocked_fraction','false_positive_rate','harmful_proposals','benign_proposals','residual_harm'] + ['harm_'+h for h in ['H-loop','H-iso','H-adv','H-power','H-energy']]
METRICS += [prefix+kind for prefix in ['proposal_type_','query_commit_type_'] for kind in ['route_change','isolate','reinstate','set_power','defer']]
METRICS += ['network_goal_queries','network_goal_opportunities','network_goal_applicable_queries','network_raw_goal_successes','network_committed_goal_successes','network_raw_goal_asr','network_committed_goal_asr']
def canonical(x):return json.dumps(x,sort_keys=True)
def signature(p,ignore=IGNORE):return canonical({k:v for k,v in p.items() if k not in ignore})
def finite(x):return isinstance(x,(float,int)) and math.isfinite(x)
def write_csv(path,rows):
 fields=list(dict.fromkeys(k for r in rows for k in r))
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def interval(x):return t_interval(x) if x else (None,None)
def holm(rows,field,n_family=None):
 tested=sorted([r for r in rows if r['status']=='tested'],key=lambda r:r['p_raw']);previous=0
 for i,r in enumerate(tested):previous=max(previous,min(1.,((len(tested) if n_family is None else n_family)-i)*r['p_raw']));r[field]=previous

def paired(reference,target,metric,metadata):
 assert set(reference)==set(target),('seed mismatch',metadata)
 seeds=sorted(reference);missing=[s for s in seeds if not finite(reference[s].get(metric)) or not finite(target[s].get(metric))]
 result={**metadata,'metric':metric,'n_expected':len(seeds),'n_pairs':len(seeds)-len(missing),'missing_seeds':canonical(missing)}
 if missing:return {**result,'status':'undefined_metric_in_pair'}
 x=[reference[s][metric] for s in seeds];y=[target[s][metric] for s in seeds];w,p,n=wilcoxon_signed_rank(x,y);mean,ci=interval([b-a for a,b in zip(x,y)])
 return {**result,'status':'tested','mean_delta':mean,'delta_ci95':ci,'p_raw':p,'w_plus':w,'n_nonzero':n}

def benchmark_tables():
 folder=ROOT/'research_v3/attack_benchmark';snapshots={s['snapshot_id']:s for s in json.loads((folder/'heldout_snapshots.json').read_text())}
 with (folder/'heldout_responses.jsonl').open() as f:rows=[json.loads(line) for line in f]
 assert len(rows)==1640 and len({r['case_id'] for r in rows})==1640
 nominal={(r['model'],r['snapshot_id']):parse_action(r['raw_action']) for r in rows if r['kind']=='nominal'}
 grouped=defaultdict(list)
 for r in rows:
  if r['kind']!='attack':continue
  s=snapshots[r['snapshot_id']];action=nominal[(r['model'],r['snapshot_id'])]
  clean_goal=(isinstance(action,RouteChange) and action.next_hop==s['attacker'] and action.dest in s['observation']['active_destinations']) if r['family']=='impersonation' else isinstance(action,Isolate) and action.node==s['target']
  r['nominal_goal_success']=bool(clean_goal)
  r['new_raw_goal_success']=r['raw_goal_success'] and not clean_goal
  r['new_shielded_goal_success']=r['shielded_goal_success'] and not clean_goal
  grouped[(r['model'],r['family'],r['template_id'],r['mode'])].append(r)
 summary=[]
 for (model,family,template,mode),items in grouped.items():
  seeds=sorted({r['seed'] for r in items});assert seeds==list(range(3000,3005))
  result={'model':model,'family':family,'template_id':template,'mode':mode,'n_states':len(items),'n_seed_clusters':5,'service_errors':sum(r['error'] is not None for r in items),'parse_errors':sum(r['parse_error'] for r in items)}
  for metric in ['raw_goal_success','shielded_goal_success','nominal_goal_success','new_raw_goal_success','new_shielded_goal_success']:
   rates=[sum(r[metric] for r in items if r['seed']==seed)/sum(r['seed']==seed for r in items) for seed in seeds]
   mean,ci=interval(rates);result[metric+'_rate']=mean;result[metric+'_ci95_t_unclipped']=ci
   # Exact bound is for ANY observed success in a seed cluster, not individual request risk.
   if not any(r[metric] for r in items):result[metric+'_any_success_per_seed_one_sided95_upper']=1-.05**(1/5)
  for metric in ['raw_harm','committed_harm']:
   result[metric+'_events']=sum(bool(r[metric]) for r in items)
   result[metric+'_unknown']=sum(r[metric] is None for r in items)
  summary.append(result)
 write_csv(OUT/'heldout_attack_summary.csv',summary);write_csv(OUT/'heldout_attack_cases.csv',rows)
 return summary

def fixed_cost_tables():
 folder=ROOT/'research_v3/fixed_observation_cost'
 assert json.loads((folder/'coverage.json').read_text())['complete']
 rows=[json.loads(line) for line in (folder/'responses.jsonl').read_text().splitlines()]
 assert len(rows)==132
 summaries=[]
 for model in sorted({r['model'] for r in rows}):
  measured=[r for r in rows if r['model']==model and r['kind']=='measured'];assert len(measured)==20
  seeds=sorted({r['seed'] for r in measured});assert seeds==list(range(3000,3005))
  summary={'model':model,'n_requests':20,'n_seed_clusters':5,'service_errors':sum(r['error'] is not None for r in measured)}
  for metric in ['latency_ms','model_server_cpu_s']:
   clusters=[sum(r[metric] for r in measured if r['seed']==seed)/4 for seed in seeds];mean,ci=interval(clusters)
   summary[metric]=mean;summary[metric+'_ci95_seed_cluster']=ci
  for key in ['prompt_tokens','completion_tokens']:
   tokens=[r['usage'].get(key) for r in measured if r['usage'].get(key) is not None]
   summary[key+'_mean']=sum(tokens)/len(tokens) if tokens else None;summary[key+'_n_valid']=len(tokens)
  summaries.append(summary)
 write_csv(OUT/'fixed_observation_cost_summary.csv',summaries);write_csv(OUT/'fixed_observation_cost_requests.csv',rows)

def main():
 OUT.mkdir(exist_ok=True);expected=json.loads((BATCH/'expected_matrix.json').read_text());accepted=json.loads((BATCH/'accepted_runs.json').read_text());assert len(expected)==len(accepted)==1190
 assert {canonical(p) for p in expected}=={canonical(r['params']) for r in accepted}
 records=[];groups=defaultdict(dict)
 for rec in accepted:
  d=ROOT/rec['directory'];cfg=json.loads((d/'run_config.json').read_text());assert cfg['status']=='finished' and cfg['run_role']=='primary' and cfg['params']==rec['params'] and not cfg['synthetic']
  assert json.loads((d/'offline_validation.json').read_text())['status']=='passed'
  for name,sha in json.loads((d/'raw_file_sha256.json').read_text()).items():assert digest(d/name)==sha,(d,name)
  row=summarise_run(d);assert row['unknown_harm_proposals']==0
  row.update(network_asr(d))
  for label in ['H-loop','H-iso','H-adv','H-power','H-energy']:row.setdefault('harm_'+label,0 if row['harm_labels_available'] else None)
  failures=read_failures(d)
  if failures:
   assert len(failures)==1
   failure=failures[0];cohort=set(failure.affected_flows);packets=read_packets(d)
   alive={p.flow_id for p in packets if p.flow_id in cohort and p.received_s is not None and failure.time_s-5<=p.received_s<failure.time_s}
   row['recovery_cohort_size']=len(cohort);row['recovery_pre_cut_live_fraction']=len(alive)/len(cohort)
   post=[p for p in packets if p.flow_id in cohort and p.sent_s>=failure.time_s]
   row['recovery_post_cut_cohort_pdr']=sum(p.received_s is not None for p in post)/len(post) if post else None
  p=rec['params'];assert p['seed'] not in groups[signature(p)];groups[signature(p)][p['seed']]=row;records.append((p,row))
 write_csv(OUT/'raw_network_metrics.csv',[r for p,r in records]);summaries=[]
 for condition,seed_rows in groups.items():
  params=json.loads(condition);wanted=list(range(1000,1005 if params['experiment']=='R4_cost' else 1010));assert sorted(seed_rows)==wanted
  summary={**params,'n_expected':len(wanted)}
  for metric in METRICS:
   vals=[r[metric] for r in seed_rows.values() if finite(r.get(metric)) and (metric!='model_server_cpu_s' or params['experiment']=='R4_cost')];mean,ci=interval(vals)
   summary.update({metric:mean,metric+'_ci95':ci,metric+'_n_valid':len(vals),metric+'_n_missing':len(wanted)-len(vals)})
  summaries.append(summary)
 write_csv(OUT/'condition_summary.csv',summaries)
 primary=[]
 for model in ['llama-3.2-1b','llama-3.1-8b']:
  for scenario,metric in [('clean','pdr'),('link_cut','recovery_rmst_s')]:
   selected={}
   for p,r in records:
    if p['experiment']=='R1_utility' and p['scenario_id']==scenario and ((p['configuration']=='shielded' and p['model']==model) or p['configuration']=='shielded_heuristic'):
     selected.setdefault(p['configuration'],{})[p['seed']]=r
   primary.append(paired(selected['shielded_heuristic'],selected['shielded'],metric,{'experiment':'R1_utility','scenario':scenario,'model':model,'comparison':'shielded LLM minus shielded heuristic'}))
 holm(primary,'p_holm_primary4',n_family=4);write_csv(OUT/'primary_paired_tests.csv',primary)
 # Match by all native/scientific parameters, ignoring only group labels and paired ids.
 variants=defaultdict(dict)
 ignore=IGNORE|{'configuration','model','experiment','scenario_id'}
 for p,r in records:variants[signature(p,ignore)].setdefault((p['experiment'],p['configuration'],p['model']),{})[p['seed']]=r
 secondary=[]
 for condition,configs in variants.items():
  for (exp,cfg,model),target in configs.items():
   if cfg!='shielded':continue
   for (bexp,bcfg,bmodel),base in configs.items():
    if bcfg=='shielded' or bmodel not in ['none',model]:continue
    if exp!=bexp and not (exp=='R1_utility' and bexp=='R2_ablation'):continue
    for metric in ['pdr','delay_p95_s','routing_overhead','harmful_proposal_rate','residual_harm_rate','recovery_rmst_s','recovery_recovered_fraction']:
     secondary.append(paired(base,target,metric,{'experiment':bexp if bexp=='R2_ablation' else exp,'model':model,'comparison':bcfg+' -> shielded','condition':condition}))
 # R0 and R4 differ deliberately in a single treatment variable.
 for exp,field,left,right in [('R0_probe_cost','reciprocal_probe',False,True),('R4_cost','timing','zero','measured')]:
  matched=defaultdict(dict)
  for p,r in records:
   eligible=p['experiment']==exp or (exp=='R0_probe_cost' and p['experiment']=='R1_utility' and p['scenario_id']=='clean' and p['configuration']=='aodv')
   if eligible:matched[signature(p,IGNORE|{'experiment','scenario_id',field})].setdefault(p[field],{})[p['seed']]=r
  for condition,levels in matched.items():
   assert set(levels)=={left,right}
   for metric in ['pdr','routing_overhead','delay_p95_s','agent_latency_ms_mean','wall_s']:
    secondary.append(paired(levels[left],levels[right],metric,{'experiment':exp,'comparison':str(left)+' -> '+str(right),'condition':condition}))
 families=defaultdict(list)
 for test in secondary:families[(test['experiment'],test['metric'])].append(test)
 for tests in families.values():holm(tests,'p_holm_experiment_metric')
 write_csv(OUT/'secondary_paired_tests.csv',secondary);attack=benchmark_tables();fixed_cost_tables()
 # Compact publication figures; full data and missing-value counts are in CSV.
 configs=[('aodv','none'),('trust_aware_aodv','none'),('shielded_defer','none'),('shielded_heuristic','none'),('unshielded','llama-3.2-1b'),('shielded','llama-3.2-1b'),('unshielded','llama-3.1-8b'),('shielded','llama-3.1-8b')]
 scenarios=['clean','link_cut','gray_hole','forged_gray','forged_sequence','false_report','injection']
 image=[]
 for cfg,model in configs:
  image.append([next(s['pdr'] for s in summaries if s['experiment']=='R1_utility' and s['scenario_id']==scenario and s['configuration']==cfg and s['model']==model) for scenario in scenarios])
 fig,ax=plt.subplots(figsize=(11,5.5));im=ax.imshow(image,vmin=0,vmax=1,cmap='viridis');ax.set_xticks(range(len(scenarios)),scenarios,rotation=25,ha='right');ax.set_yticks(range(len(configs)),[c+(' '+m if m!='none' else '') for c,m in configs])
 for i,row in enumerate(image):
  for j,v in enumerate(row):ax.text(j,i,f'{v:.3f}',ha='center',va='center',color='white' if v<.5 else 'black',fontsize=8)
 fig.colorbar(im,ax=ax,label='PDR, mean across 10 seeds');fig.tight_layout();fig.savefig(OUT/'r1_delivery.pdf');fig.savefig(OUT/'r1_delivery.png',dpi=180);plt.close(fig)
 latex=['\\begin{tabular}{llrr}','Scenario & Configuration & PDR & 95\\% CI half-width \\\\','\\hline']
 for s in summaries:
  if s['experiment']=='R1_utility':latex.append(f"{s['scenario_id'].replace('_', ' ')} & {(s['configuration']+' '+s['model']).replace('_',' ')} & {s['pdr']:.4f} & {s['pdr_ci95']:.4f} \\\\")
 latex+=['\\end{tabular}'];(OUT/'r1_delivery_table.tex').write_text('\n'.join(latex)+'\n')
 report=['# Kết quả research-v3','',f'Đã xác minh {len(accepted)}/{len(expected)} lượt mạng chính; toàn bộ case đúng expected matrix, SHA archive hợp lệ. Không gộp pilot hoặc các phiên bản trước.','', '## Bốn tương phản chính','']
 for t in primary:
  if t['status']!='tested':report.append(f"- {t['model']} / {t['scenario']}: metric thiếu, không kiểm định.");continue
  favorable=t['mean_delta']>0 if t['metric']=='pdr' else t['mean_delta']<0
  conclusion='ủng hộ cải thiện so với heuristic' if favorable and t['p_holm_primary4']<.05 else 'chưa chứng minh cải thiện so với heuristic'
  report.append(f"- {t['model']} / {t['scenario']}: delta {t['mean_delta']:.5g} ± {t['delta_ci95']:.5g} (95% CI half-width), Holm p={t['p_holm_primary4']:.5g}; {conclusion}.")
 report+=['','## Giới hạn diễn giải','','Kết quả không có ý nghĩa thống kê không chứng minh tương đương. Zero observed harm/ASR không chứng minh rủi ro bằng0. Benchmark injection là một quyết định trên state cố định, không phải rollout. CI qua 5 seed counterfactual còn rộng. Các guard phụ thuộc freshness/evidence cục bộ và điều kiện mô phỏng; xem PROTOCOL_VI.md. Khi LLM không vượt heuristic, phải thu hẹp claim về giá trị autonomy, không chỉ trình bày chỉ số safety.','','CSV chứa n_valid/n_missing, fallback harm, cache audit, paired effects và lỗi dịch vụ. R4 latency là Mac Studio với model resident; không đại diện thiết bị MANET.']
 (OUT/'RESULTS_VI.md').write_text('\n'.join(report)+'\n')
 dump(OUT/'coverage.json',{'complete':True,'expected':1190,'accepted':len(accepted),'conditions':len(summaries),'primary_tests':4,'heldout_attack_queries':1640,'fixed_cost_measured_queries':120,'fixed_cost_warmup_queries':12,'source_manifest_sha256':digest(ROOT/'environment/research_v31_frozen_inputs.json'),'analysis_code_sha256':digest(Path(__file__))})
 artifacts={str(p.relative_to(OUT)):digest(p) for p in OUT.iterdir() if p.is_file() and p.name!='artifact_sha256.json'};dump(OUT/'artifact_sha256.json',artifacts)
 print('FINAL RESEARCH ANALYSIS COMPLETE',flush=True)
if __name__=='__main__':main()
