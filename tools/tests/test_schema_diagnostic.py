"""Check diagnostic isolation and honest recording of failed service calls."""
from pathlib import Path
from types import SimpleNamespace
import fcntl
import importlib.util
import json
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('artifact_schema_diagnostic', ROOT / 'tools/schema_diagnostic.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / 'environment').mkdir()
    (tmp_path / 'environment/model_servers.json').write_text(json.dumps({'llama-3.2-1b': {'port': 19081}}))
    monkeypatch.setattr(diag, 'ROOT', tmp_path)
    return tmp_path

def test_running_replication_blocks_all_diagnostic_requests(project, monkeypatch):
    batch = project / 'runs/research_v31_primary'
    batch.mkdir(parents=True)
    def unexpected_health(port):
        raise AssertionError('No server requests are allowed while a replication holds the lock')
    monkeypatch.setattr(diag, 'healthy', unexpected_health)
    with (batch / 'artifact_replication.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit, match='full replication is running'):
            diag.run(['llama-3.2-1b'])
    assert not (project / 'runs/artifact_schema_diagnostic').exists()

def test_service_errors_are_recorded_without_fabricating_success(project, monkeypatch):
    calls = []
    class FailedAgent:
        def __init__(self, config, system_prompt):
            assert config.constraint == 'json_schema'
        def propose(self, observation):
            calls.append(observation)
            return SimpleNamespace(raw_text='invalid JSON', error='service unavailable', latency_ms=0.)
    monkeypatch.setattr(diag, 'healthy', lambda port: None)
    monkeypatch.setattr(diag, 'LLMAgent', FailedAgent)
    out, report = diag.run(['llama-3.2-1b'])
    assert len(calls) == report['n_recorded'] == report['n_expected'] == 5
    assert report['service_errors'] == 5 and report['schema_valid'] == report['expected_action_reproduced'] == 0
    assert len((out / 'responses.jsonl').read_text().splitlines()) == 5
    assert json.loads((out / 'COMPLETE.json').read_text()) == report
