"""Offline integrity, harm-oracle and packet cross-checks for real ns-3 output."""
import csv,gzip,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
from guarded_autonomy.decision_log import HashChainLog
from guarded_autonomy.ns3.adapters import _need, _open_text
from guarded_autonomy.ns3.bridge import _snapshot_from_json
from guarded_autonomy.schemas import RouteChange,SetPower,parse_action
from guarded_autonomy.simulation.harm import HarmOracle


def validate(directory, write_report=True):
    config=json.loads((directory/'run_config.json').read_text())
    assert config['status']=='finished' and config['synthetic'] is False
    scenario=json.loads((directory/'scenario_summary.json').read_text())
    assert scenario['completed'] and scenario['synthetic'] is False
    with _open_text(_need(directory,'decisions.jsonl')) as stream:
        records=[json.loads(line) for line in stream if line.strip()]
    anchors=json.loads((directory/'ns3_anchors.json').read_text())
    chain_length=0
    for node,anchor in anchors.items():
        chain=HashChainLog.load_jsonl(directory/f'chain-node-{node}.jsonl')
        assert chain.verify(anchor['head']),('chain mismatch',node)
        local=[r for r in records if r['node']==int(node)]
        assert len(chain.entries)==anchor['length']==len(local),('log length',node)
        for entry,record in zip(chain.entries,local):
            body=json.loads(entry['body'])
            assert body['node']==record['node'] and body['tier']==record['tier']
            assert body['committed']==record['action'] and body['violated']==record['violated']
        chain_length+=len(chain.entries)
    assert chain_length==scenario['base_commit_checks']+scenario['agent_decisions']
    decisions={(record['node'],float(record.get('proposal_t',record['t']))):record for record in records if record.get('event')!='base_commit'}
    proposals={key:record for key,record in decisions.items() if record.get('is_proposal')}
    labelled=0;oracle=HarmOracle();commit_labels=0
    def labels(truth,action):
        if action is None:return []
        if 'destinations' in truth:
            options=truth['destinations']
            selected=([options[str(action.dest)]] if isinstance(action,RouteChange) and str(action.dest) in options
                      else [] if isinstance(action,RouteChange) else list(options.values()) if isinstance(action,SetPower)
                      else list(options.values())[:1])
            snaps=[_snapshot_from_json({**truth.get('shared',{}),**item}) for item in selected]
        else:snaps=[_snapshot_from_json(truth)]
        return sorted(set().union(*(oracle.label(s,entry['node'],action) for s in snaps))) if snaps else None
    if (directory/'oracle.jsonl.gz').exists():
        with gzip.open(directory/'oracle.jsonl.gz','rt') as stream:
            for line in stream:
                entry=json.loads(line);decision=decisions[(entry['node'],float(entry['t']))]
                if entry.get('is_proposal',True):
                    expected=labels(entry['oracle'],parse_action(entry['proposal']))
                    assert expected is not None and decision['harm']==expected,('harm mismatch',decision,expected)
                    labelled+=1
                if entry.get('committed') is not None:
                    expected=labels(entry['oracle'],parse_action(entry['committed']))
                    assert expected is not None and decision['committed_harm']==expected,('commit harm mismatch',decision,expected)
                    commit_labels+=1
        assert labelled==len(proposals),'proposal ground-truth coverage incomplete'
    expected_commits=sum(record.get('action') is not None for record in decisions.values())
    assert commit_labels==expected_commits,('committed action label coverage incomplete',commit_labels,expected_commits)
    with _open_text(_need(directory,'packets.csv'),newline='') as stream:packets=list(csv.DictReader(stream))
    assert len(packets)==scenario['packet_records']
    assert len({(r['flow_id'],r['packet_id']) for r in packets})==len(packets)
    for row in packets:
        if row['received_s']:assert float(row['received_s'])>=float(row['sent_s'])
    delivered=sum(bool(row['received_s']) for row in packets)
    with _open_text(_need(directory,'flowmonitor.xml')) as stream:tree=ET.parse(stream)
    root=tree.getroot()
    classifiers={r.attrib['flowId']:r.attrib for r in root.findall('./Ipv4FlowClassifier/Flow')}
    data_ids={key for key,row in classifiers.items() if int(row.get('protocol',0))==17 and 9000<=int(row.get('destinationPort',0))<9000+len(scenario['flows'])}
    for ident in data_ids:
        classifier=classifiers[ident];flow=int(classifier['destinationPort'])-9000
        source,sink=scenario['flows'][flow]
        assert classifier['sourceAddress']==f'10.7.0.{source+1}',('unexpected IPv4 source',ident,classifier)
        assert classifier['destinationAddress']==f'10.7.0.{sink+1}',('unexpected IPv4 sink',ident,classifier)
    flow_rx=sum(int(r.attrib['rxPackets']) for r in root.findall('./FlowStats/Flow') if r.attrib['flowId'] in data_ids)
    assert flow_rx==delivered,('FlowMonitor receiver count differs',flow_rx,delivered)
    audit_path=directory/'daemon_audits.jsonl'
    if audit_path.exists() or audit_path.with_name(audit_path.name+'.gz').exists():
        with _open_text(_need(directory,'daemon_audits.jsonl')) as inp:audits=[json.loads(line) for line in inp if line.strip()]
        assert len(audits)==scenario['agent_decisions'],('daemon audit coverage differs',len(audits),scenario['agent_decisions'])
        for audit in audits:
            assert audit['node']==audit['cache_audit']['node']
            assert set(audit['daemon_neighbours'])==set(audit['cache_audit']['cached_neighbours'])
    report={'status':'passed','chains_verified':len(anchors),'decisions_verified':chain_length,
            'oracle_proposals_recomputed':labelled,'committed_labels_recomputed':commit_labels,'packet_rows':len(packets),'delivered_packets':delivered,
            'flowmonitor_delivered_packets':flow_rx,'counterfactual_labels_match':True}
    if write_report:(directory/'offline_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    path=Path(sys.argv[1])
    directories=[path] if (path/'run_config.json').exists() else [p.parent for p in path.rglob('run_config.json')]
    for directory in sorted(directories):
        cfg=json.loads((directory/'run_config.json').read_text())
        if cfg.get('status')!='finished':continue
        print(directory.name,validate(directory),flush=True)
