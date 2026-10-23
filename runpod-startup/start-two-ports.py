#!/usr/bin/env python3
"""Start missing ComfyUI instances, preserving occupied ports and user data."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request


def healthy(port):
    try:
        with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/system_stats', timeout=2) as r:
            data = json.load(r)
        return isinstance(data, dict) and 'system' in data and 'devices' in data
    except Exception:
        return False


def available(port):
    try:
        with socket.socket() as s:
            s.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False


def main():
    root = Path(os.environ['COMFY_ROOT'])
    help_run = subprocess.run([sys.executable, str(root / 'main.py'), '--help'], cwd=root,
                              capture_output=True, text=True, timeout=60)
    if help_run.returncode:
        print('ComfyUI environment check failed; no services changed.')
        print((help_run.stderr or help_run.stdout)[-4000:])
        return 1
    required = ['--listen', '--port', '--user-directory', '--input-directory', '--output-directory', '--temp-directory']
    if any(flag not in help_run.stdout for flag in required):
        print('Installed ComfyUI lacks required separate-instance options. No services changed.')
        return 1
    pending = {}
    failed = []
    for port in (8188, 8189):
        if healthy(port):
            print(str(port) + ': existing ComfyUI responds; preserved.', flush=True)
            continue
        if not available(port):
            print(str(port) + ': occupied but not responding as ComfyUI; preserved. Inspect its existing log.', flush=True)
            failed.append(port)
            continue
        instance = Path(os.environ.get('COMFY_INSTANCE_' + str(port), '/workspace/comfy' + str(port)))
        if not instance.is_absolute():
            raise ValueError('Instance directory must be absolute')
        other_port = 8189 if port == 8188 else 8188
        other = Path(os.environ.get('COMFY_INSTANCE_' + str(other_port), '/workspace/comfy' + str(other_port)))
        if instance.resolve() == other.resolve():
            raise ValueError('8188 and 8189 must have separate instance directories')
        for folder in ('user', 'input', 'output', 'temp'):
            (instance / folder).mkdir(parents=True, exist_ok=True)
        args = [sys.executable, str(root / 'main.py'), '--listen', '0.0.0.0', '--port', str(port)]
        for flag, folder in [('--user-directory', 'user'), ('--input-directory', 'input'),
                             ('--output-directory', 'output'), ('--temp-directory', 'temp')]:
            args += [flag, str(instance / folder)]
        if '--database-url' in help_run.stdout:
            args += ['--database-url', 'sqlite:///' + str(instance / 'user' / 'comfyui.db')]
        log_path = instance / ('comfy' + str(port) + '.log')
        with log_path.open('ab', buffering=0) as log:
            proc = subprocess.Popen(args, cwd=root, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True, close_fds=True)
        (instance / 'launcher-pid.txt').write_text(str(proc.pid) + '\n')
        pending[port] = (proc, log_path)
        print(str(port) + ': starting; log ' + str(log_path), flush=True)
    deadline = time.monotonic() + 90
    while pending and time.monotonic() < deadline:
        for port, (proc, log_path) in list(pending.items()):
            if healthy(port):
                print(str(port) + ': /system_stats responded successfully.', flush=True)
                del pending[port]
            elif proc.poll() is not None:
                print(str(port) + ': process exited. Inspect ' + str(log_path), flush=True)
                failed.append(port)
                del pending[port]
        if pending:
            time.sleep(2)
    for port, (_, log_path) in pending.items():
        print(str(port) + ': not ready within 90 seconds; process left running. Inspect ' + str(log_path), flush=True)
        failed.append(port)
    print('Expose BOTH 8188 and 8189 as HTTP ports in RunPod. Serving checks are local, not proxy/GPU proof.', flush=True)
    return int(bool(failed))


if __name__ == '__main__':
    sys.exit(main())
