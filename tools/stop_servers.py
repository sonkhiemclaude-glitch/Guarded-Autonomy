"""Stop only model processes whose executable and exact alias belong to this checkout."""
from pathlib import Path
import json
import os
import re
import signal
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def read_process(pid):
    command = subprocess.run(['/bin/ps', '-ww', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout.strip()
    if not command:
        return None
    executable = subprocess.run(['/bin/ps', '-ww', '-p', str(pid), '-o', 'comm='], capture_output=True, text=True).stdout.strip()
    return executable, command

def owns_process(executable, command, binary, alias):
    if not executable or Path(executable).resolve() != binary.resolve():
        return False
    return re.search(r'(?:^|\s)--alias(?:=|\s+)' + re.escape(alias) + r'(?=\s|$)', command) is not None

def main():
    binary = ROOT / 'vendor/llama.cpp/build/bin/llama-server'
    for name in ['model_servers', 'throughput_servers']:
        path = ROOT / f'environment/{name}.json'
        if not path.exists():
            continue
        for alias, record in json.loads(path.read_text()).items():
            pid = int(record['pid'])
            if pid <= 0:
                raise SystemExit('Refusing invalid server PID')
            process = read_process(pid)
            if process is None:
                continue
            if not owns_process(*process, binary, alias):
                raise SystemExit(f'Refusing PID {pid}: process is not this checkout\'s {alias} server')
            os.kill(pid, signal.SIGTERM)
            print('Stopped', alias, pid)
        path.unlink()

if __name__ == '__main__':
    main()
