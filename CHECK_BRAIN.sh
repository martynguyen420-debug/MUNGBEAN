#!/usr/bin/env bash
set -euo pipefail

POWER_DIR=/workspace/ComfyUI/models/LLM/powerful-brain
FAST_DIR=/workspace/ComfyUI/models/LLM
failed=0

echo "=== MUNGBEAN brain inventory ==="
find "$POWER_DIR" "$FAST_DIR" -maxdepth 1 -type f \
  \( -iname '*Qwen*3.5*27B*.gguf' -o -iname 'mmproj*27B*.gguf' -o -iname '*Qwen*3.5*9B*.gguf' -o -iname 'mmproj-BF16.gguf' \) \
  -printf '%s %p\n' 2>/dev/null | sort -nr | while read -r bytes file; do
    printf '%8s  %s\n' "$(numfmt --to=iec "$bytes")" "$file"
  done

MODEL="$(find "$POWER_DIR" -maxdepth 1 -type f -iname '*Qwen*3.5*27B*Q4_K_M*.gguf' ! -iname 'mmproj*' -print -quit 2>/dev/null || true)"
MMPROJ="$(find "$POWER_DIR" -maxdepth 1 -type f -iname 'mmproj*Qwen*3.5*27B*.gguf' -print -quit 2>/dev/null || true)"

if [[ -s "$MODEL" && -s "$MMPROJ" ]]; then
  echo "OK  Preferred 27B multimodal brain pair found."
else
  echo "MISSING  Preferred Qwen3.5-27B Q4_K_M + mmproj pair."
  failed=1
fi

if curl -fsS http://127.0.0.1:8090/v1/models >/tmp/mungbean-brain-models.json 2>/dev/null; then
  echo "OK  Brain API is responding on port 8090"
  cat /tmp/mungbean-brain-models.json
  echo
else
  echo "INFO  Brain API is not running. Start ./START_BRAIN.sh"
fi

exit "$failed"
