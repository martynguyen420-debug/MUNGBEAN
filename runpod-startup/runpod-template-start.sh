#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
BUNDLE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${COMFY_ROOT:-/workspace/runpod-slim/ComfyUI}"
PY="${COMFY_PYTHON:-}"
if [[ -z "$PY" ]]; then
  for candidate in "$ROOT/.venv-cu128/bin/python" /workspace/runpod-slim/.venv-cu128/bin/python; do
    if [[ -x "$candidate" ]]; then PY="$candidate"; break; fi
  done
fi
STATE="${RUNPOD_STATE:-/workspace/.runpod-startup}"
mkdir -p "$STATE"
exec 9>"$STATE/start.lock"
flock -n 9 || { echo 'Another startup instance owns the lock; exiting.'; exit 0; }
exec > >(tee -a "$STATE/startup.log") 2>&1
echo "Startup $(date -u +%FT%TZ)"
[[ -f "$ROOT/main.py" && -x "$PY" ]] || { echo "Missing ComfyUI or existing CUDA environment: $ROOT / $PY"; exit 1; }
# A occupied 8188 is never killed or replaced. 8189 is never probed or changed.
if ! "$PY" -c 'import socket; s=socket.socket(); s.bind(("0.0.0.0",8188)); s.close()'; then
  echo '8188 is already occupied. Exiting without touching the existing process.'; exit 1
fi
export COMFY_ROOT="$ROOT" RUNPOD_STATE="$STATE"
if ! "$PY" "$BUNDLE/setup.py" "$BUNDLE/models.lock.json" "$BUNDLE/nodes.lock.json"; then
  echo 'Some setup items failed. See setup-status.json; starting available ComfyUI anyway.'
fi
# Isolated BF16 downloader (optional). It runs alongside the existing server.
# Never installs/replaces the GGUF loader or any existing model.
if [[ -n "${CIVITAI_TOKEN:-}" && "${AUTO_KREA_BF16:-1}" != "0" ]]; then
  (
    exec 9>&-  # Child must not inherit the main startup lock.
    exec 7>"$STATE/krea-bf16-auto.lock"
    flock -n 7 || exit 0
    exec "$PY" "$BUNDLE/civitai-kreanoct-bf16.py"
  ) >>"$STATE/krea-bf16-auto.log" 2>&1 </dev/null &
  echo "Krea Noct BF16 download runs separately; see $STATE/krea-bf16-auto.log"
else
  echo 'Krea Noct BF16 skipped (set CIVITAI_TOKEN in RunPod environment).'
fi
cd "$ROOT"
INSTANCE="${COMFY_INSTANCE_DIR:-/workspace/comfy8188}"
mkdir -p "$INSTANCE"/{user,input,output,temp}
# No core upgrade, torch/CUDA reinstall, broad requirements install or 8189 service management.
exec "$PY" main.py --listen 0.0.0.0 --port 8188 \
  --user-directory "$INSTANCE/user" \
  --input-directory "$INSTANCE/input" \
  --output-directory "$INSTANCE/output" \
  --temp-directory "$INSTANCE/temp" \
  --database-url "sqlite:///$INSTANCE/user/comfyui.db"
