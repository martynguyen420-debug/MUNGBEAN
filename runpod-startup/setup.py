#!/usr/bin/env python3
"""Standard-library setup helper. No HF SDK or dependency resolver needed."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(path):
    s = path.stat()
    return [s.st_size, s.st_mtime_ns, s.st_ino, s.st_dev]


def verified(path, asset, receipts):
    if not path.is_file() or path.stat().st_size != asset['size']:
        return False
    key = str(path.resolve())
    record = [asset['sha256'], fingerprint(path)]
    if os.environ.get('VERIFY_ALL') != '1' and receipts.get(key) == record:
        return True
    if digest(path) != asset['sha256']:
        return False
    receipts[key] = record
    return True


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_json(path, value):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(tmp, path)


def metadata(asset):
    kind = asset.get('kind', 'models')
    url = ('https://huggingface.co/api/' + kind + '/' + asset['repo'] + '/revision/' +
           asset['revision'] + '?blobs=true')
    headers = {'User-Agent': 'runpod-persistent-startup/1'}
    if os.environ.get('HF_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['HF_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as r:
        data = json.load(r)
    f = next(x for x in data['siblings'] if x['rfilename'] == asset['path'])
    assert data['sha'] == asset['revision'], 'Revision changed'
    assert f['lfs']['sha256'] == asset['sha256'], 'Publisher hash differs'
    assert f['lfs']['size'] == asset['size'], 'Publisher size differs'
    return 'https://huggingface.co/' + ('datasets/' if kind == 'datasets' else '') + asset['repo'] + '/resolve/' + asset['revision'] + '/' + urllib.parse.quote(asset['path'], safe='/')


def download(asset, dest, url):
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + '.part')
    if part.exists() and part.stat().st_size > asset['size']:
        raise RuntimeError('Oversized partial preserved: ' + str(part))
    remaining = asset['size'] - (part.stat().st_size if part.exists() else 0)
    if shutil.disk_usage(dest.parent).free < remaining + 1024**3:
        raise RuntimeError('Insufficient free storage for ' + dest.name)
    if remaining:
        # Token travels on stdin, not command line or disk. Curl follows HF CDN redirects
        # without forwarding Authorization to a different host.
        config = ''
        token = os.environ.get('HF_TOKEN', '')
        if token:
            if any(c in token for c in '\r\n"\\'):
                raise RuntimeError('Invalid HF_TOKEN format')
            config = 'header = "Authorization: Bearer ' + token + '"\n'
        command = ['curl', '--config', '-', '--fail', '--location', '--silent', '--show-error',
                   '--connect-timeout', '30', '--speed-limit', '1024', '--speed-time', '120',
                   '--retry', '3', '--retry-delay', '5', '--continue-at', '-', '--output', str(part), url]
        result = subprocess.run(command, input=config, text=True)
        if result.returncode:
            raise RuntimeError('Download unavailable (possibly gated: accept license and set HF_TOKEN). Partial retained: ' + dest.name)
    if part.stat().st_size != asset['size'] or digest(part) != asset['sha256']:
        # Do not automatically download another many-GB copy each launch.
        raise RuntimeError('Partial failed integrity check; preserved for inspection: ' + str(part))
    os.replace(part, dest)


def install_node(root, state, node):
    dest = root / 'custom_nodes' / node['name']
    if dest.exists():
        head = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip()
        if head != node['revision']:
            raise RuntimeError('Existing node revision differs; preserved without updating: ' + str(dest))
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        stage = dest.with_name(dest.name + '.installing')
        if stage.exists():
            raise RuntimeError('Interrupted node staging directory preserved: ' + str(stage))
        subprocess.run(['git', 'init', str(stage)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['git', '-C', str(stage), 'remote', 'add', 'origin', node['url']], check=True)
        subprocess.run(['git', '-C', str(stage), 'fetch', '--depth', '1', 'origin', node['revision']], check=True)
        subprocess.run(['git', '-C', str(stage), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
        os.replace(stage, dest)
    # Install ONLY missing small dependencies, with no dependency resolution. Existing
    # packages, especially torch/numpy/CUDA, are never upgraded or downgraded.
    for package, version in node['missing_dependencies'].items():
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                            '--no-deps', package + '==' + version], check=True)
    subprocess.run([sys.executable, '-c', 'import torch,numpy,gguf,sentencepiece,google.protobuf,yaml,requests,tqdm; from importlib.metadata import version; assert tuple(int(x) for x in version("gguf").split(".")[:2]) >= (0,13), "gguf too old; preserved existing install"'], check=True)


def main():
    root = Path(os.environ.get('COMFY_ROOT', '/workspace/runpod-slim/ComfyUI'))
    state = Path(os.environ.get('RUNPOD_STATE', '/workspace/.runpod-startup'))
    state.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(sys.argv[1]).read_text())
    nodes = json.loads(Path(sys.argv[2]).read_text())
    receipts_path = state / 'verified-files.json'
    receipts = read_json(receipts_path, {})
    results = []
    # Check installed core source without changing it. Actual GPU workflow validation
    # is still required on the target pod; these checks only catch obvious old cores.
    core_sources = [root / 'comfy' / 'supported_models.py', root / 'comfy' / 'sd.py']
    source = '\n'.join(p.read_text(errors='replace') for p in core_sources if p.exists()).lower()
    if any(token not in source for token in ('klein', 'qwen_image', 'krea2')):
        results.append({'item': 'ComfyUI core', 'status': 'failed', 'reason': 'Core source lacks Klein/Qwen/Krea2 support. Existing core preserved; update separately in a tested environment.'})
        save_json(state / 'setup-status.json', results)
        print(results, flush=True)
        return 1
    for node in nodes:
        try:
            install_node(root, state, node)
            results.append({'item': node['name'], 'status': 'ready'})
        except Exception as e:
            print('NODE:', str(e), flush=True)
            results.append({'item': node['name'], 'status': 'failed', 'reason': str(e)})
    pending = []
    for a in manifest['assets']:
        try:
            relative = Path(a['destination'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe manifest destination')
            dest = root / 'models' / relative
            if verified(dest, a, receipts):
                results.append({'item': a['destination'], 'status': 'reused'})
                continue
            if dest.exists():
                raise RuntimeError('Existing mismatching file preserved; no overwrite: ' + str(dest))
            # Reuse older placement in models/unet or another models subfolder by
            # checking exact size + SHA, then linking instead of copying/downloading.
            candidates = list((root / 'models').rglob(dest.name))
            found = next((p for p in candidates if p != dest and verified(p, a, receipts)), None)
            if found:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(found.resolve())
                verified(dest, a, receipts)
                results.append({'item': a['destination'], 'status': 'linked-existing'})
                continue
            url = metadata(a)  # Check EVERY missing path/hash before any model download.
            pending.append((a, dest, url))
        except Exception as e:
            results.append({'item': a['destination'], 'status': 'failed', 'reason': str(e)})
            print('MODEL:', a['destination'], str(e), flush=True)
    for a, dest, url in pending:
        try:
            print('DOWNLOAD:', a['destination'], a['size'], flush=True)
            download(a, dest, url)
            receipts[str(dest.resolve())] = [a['sha256'], fingerprint(dest)]
            results.append({'item': a['destination'], 'status': 'downloaded-verified'})
        except Exception as e:
            results.append({'item': a['destination'], 'status': 'failed', 'reason': str(e)})
            print('MODEL:', str(e), flush=True)
        finally:
            save_json(receipts_path, receipts)
    for item in manifest.get('disabled', []):
        results.append({'item': item['name'], 'status': 'disabled', 'reason': item['reason']})
    save_json(receipts_path, receipts)
    save_json(state / 'setup-status.json', results)
    print(json.dumps(results, indent=2), flush=True)
    return int(any(x['status'] == 'failed' for x in results))


if __name__ == '__main__':
    sys.exit(main())
