#!/usr/bin/env bash
set -euo pipefail

MODEL=/workspace/ComfyUI/models/LLM/powerful-brain/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf
MMPROJ=/workspace/ComfyUI/models/LLM/powerful-brain/mmproj-Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-f16.gguf

failed=0
for file in "$MODEL" "$MMPROJ"; do
  if [[ -s "$file" ]]; then
    echo "OK  $(du -h "$file" | cut -f1)  $file"
  else
    echo "MISSING  $file"
    failed=1
  fi
done

if curl -fsS http://127.0.0.1:8090/v1/models >/dev/null 2>&1; then
  echo "OK  Brain API is responding on port 8090"
else
  echo "INFO  Files checked, but Brain API is not running. Start ./START_BRAIN.sh"
fi

exit "$failed"
