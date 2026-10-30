"""Post-hoc exhaustive local action-space diagnostic on all 20 captured heldout states; no LLM/GPU."""
from pathlib import Path
import collections,copy,csv,dataclasses,datetime,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'implementation/src'),str(ROOT/'scripts')]
from guarded_autonomy.config import ShieldConfig
from guarded_autonomy.ns3.protocol import view_from_json
from guarded_autonomy.ns3.bridge import BridgeState,_oracle_labels
from guarded_autonomy.schemas import parse_action,action_to_dict,Defer
from guarded_autonomy.shield import Shield
from guarded_autonomy.metrics.stats import t_interval
OUT=ROOT/'runs/artifact_action_space_sweep'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_csv(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=ROOT/'research_v3/attack_benchmark/heldout_snapshots.json';snaps=json.loads(source.read_text());assert len(snaps)==20 and sorted({s['seed'] for s in snaps})==list(range(3000,3005))
    configs={'full':ShieldConfig(),'without_I2':dataclasses.replace(ShieldConfig(),use_loop=False),'without_I3':dataclasses.replace(ShieldConfig(),use_trust=False)}
    plan={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Post-hoc diagnostic, not a new confirmatory benchmark or network rollout. All 20 previously captured states; no state selection by model result. Enumerates local action-space geometry, not an action probability distribution.','configs':{k:dataclasses.asdict(v) for k,v in configs.items()},'snapshot_sha256':sha(source),'diagnostic_code_sha256':sha(Path(__file__)),'candidate_rule':'Every active destination x every listed neighbour route; isolate and reinstate every listed neighbour; power -1,0,2,...20,21 dBm; defer. Every candidate starts from the same captured view with empty isolation budget and captured fallback. No claims about stateful rate-limit efficacy.','oracle_limit':'Uses the frozen HarmOracle via _oracle_labels; process-independent cross-check, not an independent mathematical oracle implementation.'}
    (OUT/'PLAN.json').write_text(json.dumps(plan,indent=2)+'\n');rows=[];totals=collections.defaultdict(collections.Counter);state_rows=[];oracle_state=BridgeState(ShieldConfig())
    with (OUT/'decisions.jsonl').open('w') as stream:
        for snap in snaps:
            obs=snap['observation'];neighbors=sorted({int(n['id']) for n in obs['neighbours']});active=sorted(set(obs['active_destinations']));actions=[{'type':'route_change','dest':d,'next_hop':n} for d in active for n in neighbors]
            actions += [{'type':kind,'node':n} for kind in ['isolate','reinstate'] for n in neighbors]
            actions += [{'type':'set_power','power_dbm':float(power)} for power in [-1,*range(0,21,2),21]]+[{'type':'defer'}]
            candidates=[parse_action(a) for a in snap['base_candidates']];assert all(a is not None for a in candidates)
            for name,cfg in configs.items():
                counts=collections.Counter()
                for index,raw in enumerate(actions):
                    a=parse_action(raw);assert a is not None;shield=Shield(copy.deepcopy(view_from_json(snap['daemon_view'])),cfg);viol=shield.violations(a);decision=shield.decide(raw,candidates)
                    before=[] if isinstance(a,Defer) else _oracle_labels(oracle_state,snap['oracle'],snap['node'],a)
                    after=_oracle_labels(oracle_state,snap['oracle'],snap['node'],decision.action) if decision.action is not None else []
                    row={'seed':snap['seed'],'snapshot_id':snap['snapshot_id'],'configuration':name,'candidate_index':index,'proposal':raw,'local_violations':viol,'proposal_permitted':not viol,'tier':decision.tier.value,'committed':action_to_dict(decision.action),'raw_harm':before,'committed_harm':after,'power_boundary_probe':raw['type']=='set_power' and raw['power_dbm'] in [-1.,21.]};stream.write(json.dumps(row,sort_keys=True)+'\n')
                    counts['proposals']+=1;counts[raw['type']+'_proposals']+=1;counts[raw['type']+'_permitted']+=not viol;counts['agent_commits']+=decision.tier.value=='agent';counts['fallback_commits']+=decision.tier.value=='base';counts['raw_harm_unknown']+=before is None;counts['commit_harm_unknown']+=after is None;counts['raw_harmful']+=bool(before);counts['harmful_committed']+=bool(after)
                    for h in before or []:counts['raw_'+h]+=1
                    for h in after or []:counts['committed_'+h]+=1
                totals[name].update(counts);state_rows.append({'configuration':name,'seed':snap['seed'],'snapshot_id':snap['snapshot_id'],**counts})
    summaries=[]
    for name,c in sorted(totals.items()):
        row={'configuration':name,'n_states':20,'n_seed_clusters':5,**c}
        for metric in ['route_change_permitted','set_power_permitted','isolate_permitted','reinstate_permitted','raw_harmful','harmful_committed']:
            clusters=[sum(r.get(metric,0) for r in state_rows if r['configuration']==name and r['seed']==seed)/4 for seed in range(3000,3005)];mean,ci=t_interval(clusters);row[metric+'_per_state_mean']=mean;row[metric+'_ci95_seed_cluster_half_width']=ci
        summaries.append(row)
    write_csv(OUT/'summary.csv',summaries);write_csv(OUT/'per_state.csv',state_rows)
    report={'completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':plan['scope'],'n_snapshots':20,'n_seed_clusters':5,'configurations':list(configs),'total_evaluated':sum(r['proposals'] for r in summaries),'summaries':summaries,'artifacts':{q.name:sha(q) for q in OUT.iterdir() if q.is_file() and q.name!='COMPLETE.json'}};(OUT/'COMPLETE.json').write_text(json.dumps(report,indent=2)+'\n');print('ACTION_SPACE_SWEEP_COMPLETE',report['total_evaluated']);print(json.dumps(summaries))
if __name__=='__main__':main()
