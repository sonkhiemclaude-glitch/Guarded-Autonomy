"""Exercise cleanup against PID reuse and aliases belonging to other processes."""
from pathlib import Path
import importlib.util
import json
import signal
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('artifact_stop_servers', ROOT / 'tools/stop_servers.py')
stop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stop)

@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / 'project with spaces'
    registry = root / 'environment/model_servers.json'
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({'llama-3.2-1b': {'pid': 4321}}))
    monkeypatch.setattr(stop, 'ROOT', root)
    killed = []
    monkeypatch.setattr(stop.os, 'kill', lambda pid, sig: killed.append((pid, sig)))
    return root, registry, killed

@pytest.mark.parametrize('case', ['alias_prefix', 'different_checkout', 'non_server', 'missing_alias'])
def test_pid_reuse_never_signals_other_processes(checkout, monkeypatch, case):
    root, registry, killed = checkout
    binary = root / 'vendor/llama.cpp/build/bin/llama-server'
    executable = str(binary)
    command = str(binary) + ' --alias llama-3.2-1b --port 19081'
    if case == 'alias_prefix':
        command = str(binary) + ' --alias llama-3.2-1b-other --port 19081'
    elif case == 'different_checkout':
        executable = str(root.parent / 'other/vendor/llama.cpp/build/bin/llama-server')
        command = executable + ' --alias llama-3.2-1b'
    elif case == 'non_server':
        executable = '/usr/bin/python3'
        command = executable + ' inspect.py --file ' + str(binary) + ' --alias llama-3.2-1b'
    elif case == 'missing_alias':
        command = str(binary) + ' --port 19081'
    monkeypatch.setattr(stop, 'read_process', lambda pid: (executable, command))
    with pytest.raises(SystemExit, match='Refusing PID'):
        stop.main()
    assert killed == [] and registry.exists()

@pytest.mark.parametrize('option', ['--alias llama-3.2-1b', '--alias=llama-3.2-1b'])
def test_own_server_is_stopped_even_with_spaces_in_checkout(checkout, monkeypatch, option):
    root, registry, killed = checkout
    binary = root / 'vendor/llama.cpp/build/bin/llama-server'
    monkeypatch.setattr(stop, 'read_process', lambda pid: (str(binary), str(binary) + ' ' + option + ' --port 19081'))
    stop.main()
    assert killed == [(4321, signal.SIGTERM)] and not registry.exists()

def test_already_exited_server_has_no_signal(checkout, monkeypatch):
    root, registry, killed = checkout
    monkeypatch.setattr(stop, 'read_process', lambda pid: None)
    stop.main()
    assert killed == [] and not registry.exists()

@pytest.mark.parametrize('pid', [0, -1])
def test_process_group_pids_are_refused(checkout, monkeypatch, pid):
    root, registry, killed = checkout
    registry.write_text(json.dumps({'llama-3.2-1b': {'pid': pid}}))
    def unexpected_read(pid):
        raise AssertionError('Invalid PID must be rejected before querying a process')
    monkeypatch.setattr(stop, 'read_process', unexpected_read)
    with pytest.raises(SystemExit, match='invalid server PID'):
        stop.main()
    assert killed == [] and registry.exists()

@pytest.mark.parametrize('option, code', [('--help', 0), ('--dry-run', 2)])
def test_help_and_unknown_options_never_stop_servers(monkeypatch, option, code):
    def unexpected_stop():
        raise AssertionError('Argument-only invocations must not stop any server')
    monkeypatch.setattr(stop, 'main', unexpected_stop)
    monkeypatch.setattr(sys, 'argv', ['stop_servers.py', option])
    with pytest.raises(SystemExit) as result:
        stop.cli()
    assert result.value.code == code
