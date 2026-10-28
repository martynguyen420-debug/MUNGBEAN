#!/usr/bin/env python3
"""Run one locked model group, or just custom nodes, without launching ComfyUI."""
import json
import os
from pathlib import Path
import sys
import tempfile

import setup as installer


def select_group(manifest, nodes, group):
    groups = json.loads((Path(__file__).parent / 'install-groups.json').read_text())
    spec = groups[group]
    wanted = set(spec['destinations'])
    assets = [a for a in manifest['assets'] if a['destination'] in wanted]
    if {a['destination'] for a in assets} != wanted:
        raise ValueError('A selected locked model is missing from the manifest')
    return spec['name'], {'schema': 1, 'assets': assets, 'disabled': []}, nodes if group == '6' else []


def main():
    bundle = Path(__file__).parent
    group = sys.argv[1]
    if group == '11':
        # Optional, manual-only PornMaster. Reuse the exact pinned shared Klein
        # encoder/VAE assets without duplicating their checksums or downloading
        # other Klein checkpoints.
        manifest = json.loads((bundle / 'pornmaster-models.lock.json').read_text())
        shared = json.loads((bundle / 'models.lock.json').read_text())
        shared_paths = {'text_encoders/qwen_3_8b.safetensors', 'vae/flux2-vae.safetensors'}
        manifest['assets'].extend(a for a in shared['assets'] if a['destination'] in shared_paths)
    else:
        lock = 'sdxl-models.lock.json' if group in {'12', '13', '14'} else 'models.lock.json'
        manifest = json.loads((bundle / lock).read_text())
    name, manifest, nodes = select_group(manifest,
                                       json.loads((bundle / 'nodes.lock.json').read_text()), group)
    print('Installing group ' + group + ': ' + name, flush=True)
    state = Path(os.environ['RUNPOD_STATE'])
    with tempfile.TemporaryDirectory(prefix='group-' + group + '-', dir=state) as temp:
        model_file = Path(temp) / 'models.json'
        node_file = Path(temp) / 'nodes.json'
        model_file.write_text(json.dumps(manifest))
        node_file.write_text(json.dumps(nodes))
        sys.argv = [str(bundle / 'setup.py'), str(model_file), str(node_file)]
        result = installer.main()
        status = state / 'setup-status.json'
        if status.exists():
            (state / ('group-' + group + '-status.json')).write_bytes(status.read_bytes())
        locations = state / 'model-locations.json'
        if locations.exists():
            (state / ('group-' + group + '-locations.json')).write_bytes(locations.read_bytes())
    print('Finished. This installer does not start or restart either ComfyUI port.', flush=True)
    return result


if __name__ == '__main__':
    sys.exit(main())
