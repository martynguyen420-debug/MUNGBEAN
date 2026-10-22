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
    name, manifest, nodes = select_group(json.loads((bundle / 'models.lock.json').read_text()),
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
    print('Finished. This installer does not start or restart either ComfyUI port.', flush=True)
    return result


if __name__ == '__main__':
    sys.exit(main())
