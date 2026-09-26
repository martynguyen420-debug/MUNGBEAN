#!/usr/bin/env bash
set -euo pipefail

DEST="${BRAIN_DIR:-/workspace/ComfyUI/models/LLM/powerful-brain}"
REPO="${BRAIN_REPO:-bartowski/Qwen_Qwen3.5-27B-GGUF}"
MODEL_FILE="${BRAIN_MODEL_FILE:-Qwen_Qwen3.5-27B-Q4_K_M.gguf}"
MMPROJ_FILE="${BRAIN_MMPROJ_FILE:-mmproj-Qwen_Qwen3.5-27B-f16.gguf}"

mkdir -p "$DEST"
echo "Installing MUNGBEAN preferred brain into $DEST"
echo "Repo: $REPO"
echo "Model: $MODEL_FILE"
echo "Vision projector: $MMPROJ_FILE"

if ! python3 -c 'import huggingface_hub' >/dev/null 2>&1; then
  python3 -m pip install --quiet --upgrade huggingface_hub
fi

python3 - "$REPO" "$MODEL_FILE" "$MMPROJ_FILE" "$DEST" <<'PY'
import shutil
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download

repo, model, mmproj, dest = sys.argv[1:]
dest = Path(dest)
dest.mkdir(parents=True, exist_ok=True)
for filename in (model, mmproj):
    target = dest / filename
    if target.is_file() and target.stat().st_size > 0:
        print(f"Already present: {target}")
        continue
    cached = Path(hf_hub_download(repo_id=repo, filename=filename))
    shutil.copy2(cached, target)
    print(f"Installed: {target} ({target.stat().st_size:,} bytes)")
PY

echo
echo "Install complete. Verify with ./CHECK_BRAIN.sh"
