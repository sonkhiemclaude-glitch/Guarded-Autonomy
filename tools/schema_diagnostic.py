"""Five explicit action-copy prompts per selected model; a transport diagnostic, not a network benchmark."""
from pathlib import Path
import argparse
import datetime
import fcntl
import hashlib
import json
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'implementation/src'))
from guarded_autonomy.agents.llm import LLMAgent, LLMEndpointConfig
from guarded_autonomy.agents.grammar import ACTION_JSON_SCHEMA, validate_against_schema
from guarded_autonomy.schemas import parse_action, action_to_dict

EXPECTED = [{'type': 'route_change', 'dest': 8, 'next_hop': 3},
            {'type': 'isolate', 'node': 3}, {'type': 'reinstate', 'node': 3},
            {'type': 'set_power', 'power_dbm': 18.0}, {'type': 'defer'}]
MODELS = ['llama-3.2-1b', 'llama-3.2-3b', 'llama-3.1-8b',
          'qwen2.5-1.5b', 'qwen2.5-3b', 'qwen2.5-7b']
SCOPE = ('Supplemental transport diagnostic using explicit copy prompts. Not a network decision, '
         'attack benchmark or primary policy-performance measurement. One attempt per action; no response-based retries.')

def healthy(port):
    with urllib.request.urlopen(f'http://127.0.0.1:{int(port)}/health', timeout=3) as response:
        if json.load(response).get('status') != 'ok':
            raise SystemExit('Selected model server is not healthy')

def run(models):
    if not models or any(model not in MODELS for model in models) or len(set(models)) != len(models):
        raise SystemExit('Select distinct supported model aliases')
    registry_path = ROOT / 'environment/model_servers.json'
    if not registry_path.exists():
        raise SystemExit('Start the selected artifact model servers first')
    registry = json.loads(registry_path.read_text())
    if any(model not in registry for model in models):
        raise SystemExit('A selected model is absent from this checkout\'s server registry')
    batch = ROOT / 'runs/research_v31_primary'
    batch.mkdir(parents=True, exist_ok=True)
    with (batch / 'artifact_replication.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A full replication is running; diagnostic requests were not submitted')
        for model in models:
            healthy(registry[model]['port'])
        out = ROOT / 'runs/artifact_schema_diagnostic' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        out.mkdir(parents=True)
        rows = []
        with (out / 'responses.jsonl').open('w') as stream:
            for model in models:
                for expected in EXPECTED:
                    prompt = 'Transport schema diagnostic, not a network decision. Return exactly this JSON action, without a reason: ' + json.dumps(expected, sort_keys=True)
                    agent = LLMAgent(LLMEndpointConfig(base_url=f'http://127.0.0.1:{int(registry[model]["port"])}', model=model,
                                     temperature=0., max_tokens=128, timeout_s=60., constraint='json_schema', extra={'seed': 90001}), system_prompt=prompt)
                    reply = agent.propose({'diagnostic': 'action_schema_branch_availability'})
                    try:
                        raw = json.loads(reply.raw_text)
                    except (ValueError, TypeError):
                        raw = None
                    parsed = parse_action(reply.raw_text)
                    valid = validate_against_schema(raw)
                    row = {'case_id': model + '/' + expected['type'], 'model': model, 'expected': expected,
                           'raw': reply.raw_text, 'error': reply.error, 'schema_valid': valid,
                           'expected_action_reproduced': bool(valid and parsed is not None and action_to_dict(parsed) == expected),
                           'latency_ms': reply.latency_ms, 'diagnostic_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                           'schema_sha256': hashlib.sha256(json.dumps(ACTION_JSON_SCHEMA, sort_keys=True).encode()).hexdigest(), 'scope': SCOPE}
                    stream.write(json.dumps(row, sort_keys=True) + '\n')
                    stream.flush()
                    rows.append(row)
        report = {'completed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'n_expected': len(models) * 5,
                  'n_recorded': len(rows), 'schema_valid': sum(row['schema_valid'] for row in rows),
                  'expected_action_reproduced': sum(row['expected_action_reproduced'] for row in rows),
                  'service_errors': sum(row['error'] is not None for row in rows),
                  'response_sha256': hashlib.sha256((out / 'responses.jsonl').read_bytes()).hexdigest(), 'scope': SCOPE}
        (out / 'COMPLETE.json').write_text(json.dumps(report, indent=2) + '\n')
        return out, report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--model', choices=MODELS)
    group.add_argument('--all', action='store_true')
    args = parser.parse_args()
    out, report = run(MODELS if args.all else [args.model])
    print(json.dumps({'directory': str(out.relative_to(ROOT)), **report}, indent=2))
    if report['service_errors']:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
