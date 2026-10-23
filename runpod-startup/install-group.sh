#!/usr/bin/env bash
set -Eeuo pipefail
BUNDLE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GROUP="${1:-}"
[[ "$GROUP" =~ ^[1-7]$ ]] || { echo 'Choose 1 through 7.'; exit 1; }
ROOT="${COMFY_ROOT:-/workspace/runpod-slim/ComfyUI}"
PY="${COMFY_PYTHON:-}"
if [[ -z "$PY" ]]; then
  for candidate in "$ROOT/.venv-cu128/bin/python" /workspace/runpod-slim/.venv-cu128/bin/python; do
    if [[ -x "$candidate" ]]; then PY="$candidate"; break; fi
  done
fi
[[ -f "$ROOT/main.py" && -x "$PY" ]] || { echo 'Existing ComfyUI/CUDA Python not found. Set COMFY_ROOT and COMFY_PYTHON.'; exit 1; }
export COMFY_ROOT="$ROOT"
export RUNPOD_STATE="${RUNPOD_STATE:-/workspace/.runpod-startup}"
mkdir -p "$RUNPOD_STATE"
exec 9>"$RUNPOD_STATE/start.lock"
flock -n 9 || { echo 'Another installer/startup is active. Wait for it to finish.'; exit 1; }
if [[ "$GROUP" == 7 ]]; then
  exec "$PY" "$BUNDLE/start-two-ports.py"
fi
exec "$PY" "$BUNDLE/manual-install.py" "$GROUP"
