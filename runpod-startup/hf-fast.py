#!/usr/bin/env python3
"""Isolated Hugging Face/Xet downloader; never changes ComfyUI's packages."""
import json
import os
from pathlib import Path
import subprocess
import sys


def runtime():
    state = Path(os.environ.get('RUNPOD_STATE', '/workspace/.runpod-startup'))
    env = state / 'hf-download-venv'
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.is_file():
        print('Preparing isolated Hugging Face download tools (ComfyUI packages unchanged).', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(env)], check=True)
    check = 'from importlib.metadata import version; import huggingface_hub,hf_xet; assert version("huggingface_hub")=="2.3.0"; assert version("hf_xet")=="1.7.0"'
    if subprocess.run([str(python), '-c', check], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                        'huggingface_hub==2.3.0', 'hf_xet==1.7.0'], check=True)
    return python


def download(asset, destination):
    # Set before importing the SDK: it reads environment options at import time.
    os.environ.setdefault('HF_XET_HIGH_PERFORMANCE', '1')
    from huggingface_hub import hf_hub_download
    import setup as installer

    dest = Path(destination)
    stage = dest.parent / '.hf-downloads' / asset['repo'].replace('/', '--') / asset['revision']
    stage.mkdir(parents=True, exist_ok=True)
    print('Hugging Face Xet download; high performance=' + os.environ['HF_XET_HIGH_PERFORMANCE'], flush=True)
    result = Path(hf_hub_download(repo_id=asset['repo'], filename=asset['path'],
                                revision=asset['revision'],
                                repo_type='dataset' if asset.get('kind') == 'datasets' else 'model',
                                local_dir=str(stage), token=os.environ.get('HF_TOKEN') or None))
    if result.stat().st_size != asset['size'] or installer.digest(result) != asset['sha256']:
        raise RuntimeError('Xet file failed size/SHA256 verification; staged file preserved: ' + str(result))
    if dest.exists():
        raise RuntimeError('Destination appeared during download; preserved without overwrite: ' + str(dest))
    os.replace(result, dest)  # Same filesystem, no second multi-GB copy.


def main():
    mode = sys.argv[1]
    if mode == '--worker':
        download(json.loads(sys.argv[2]), sys.argv[3])
        return 0
    python = runtime()
    os.environ.setdefault('HF_XET_HIGH_PERFORMANCE', '1')
    if mode == 'download':
        command = [str(python), str(Path(__file__).resolve()), '--worker', *sys.argv[2:]]
    elif mode == 'extra' and sys.argv[2:] in [['9'], ['10']]:
        command = [str(python), str(Path(__file__).with_name('download-extra-models.py')), sys.argv[2]]
    else:
        raise ValueError('Use download ASSET_JSON DESTINATION or extra 9/10')
    return subprocess.run(command, env=os.environ).returncode


if __name__ == '__main__':
    sys.exit(main())
