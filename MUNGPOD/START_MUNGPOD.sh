#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
COMFY_ROOT="$(printenv COMFY_ROOT || true)"
COMFY_URL="$(printenv COMFY_URL || true)"
COMFY_PYTHON="$(printenv COMFY_PYTHON || true)"
MUNGPOD_PORT="$(printenv MUNGPOD_PORT || true)"
MUNGPOD_HOST="$(printenv MUNGPOD_HOST || true)"
MUNGPOD_VENV="$(printenv MUNGPOD_VENV || true)"

if [[ -z "$COMFY_ROOT" ]]; then
  for candidate in /workspace/runpod-slim/ComfyUI /workspace/ComfyUI /workspace-global/runpod-slim/ComfyUI /workspace-global/ComfyUI; do
    if [[ -f "$candidate/main.py" ]]; then COMFY_ROOT="$candidate"; break; fi
  done
fi
if [[ -z "$COMFY_ROOT" ]]; then COMFY_ROOT=/workspace/runpod-slim/ComfyUI; fi
if [[ -z "$COMFY_URL" ]]; then COMFY_URL=http://127.0.0.1:8188; fi
if [[ -z "$MUNGPOD_PORT" ]]; then MUNGPOD_PORT=7866; fi
if [[ -z "$MUNGPOD_HOST" ]]; then MUNGPOD_HOST=0.0.0.0; fi
if [[ -z "$MUNGPOD_VENV" ]]; then MUNGPOD_VENV=/workspace/.mungpod-venv; fi
if [[ -z "$COMFY_PYTHON" ]]; then
  for candidate in "$COMFY_ROOT/.venv-cu128/bin/python" "$COMFY_ROOT/../.venv-cu128/bin/python"; do
    if [[ -x "$candidate" ]]; then COMFY_PYTHON="$candidate"; break; fi
  done
fi
if [[ -z "$COMFY_PYTHON" ]]; then COMFY_PYTHON="$(command -v python3)"; fi
export COMFY_ROOT COMFY_URL COMFY_PYTHON MUNGPOD_PORT MUNGPOD_HOST
mkdir -p "$MUNGPOD_VENV"
if [[ ! -x "$MUNGPOD_VENV/bin/python" ]]; then python3 -m venv "$MUNGPOD_VENV"; fi
"$MUNGPOD_VENV/bin/python" -m pip install --disable-pip-version-check -r "$APP_DIR/requirements.txt"
exec "$MUNGPOD_VENV/bin/python" "$APP_DIR/MUNGPOD.py"
