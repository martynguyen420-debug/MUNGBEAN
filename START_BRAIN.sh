#!/usr/bin/env bash
set -euo pipefail

POWER_DIR=/workspace/ComfyUI/models/LLM/powerful-brain
FAST_DIR=/workspace/ComfyUI/models/LLM
POWER_MODEL="$POWER_DIR/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"
POWER_MMPROJ="$POWER_DIR/mmproj-Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-f16.gguf"
FAST_MODEL="$FAST_DIR/Qwen3.5-9B-Claude-4.6-OS-AV-H-UNCENSORED-THINK-D_AU-Q4_K_M-imat.gguf"
FAST_MMPROJ="$FAST_DIR/mmproj-BF16.gguf"

LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || true)}"
if [[ -z "$LLAMA_SERVER" ]]; then
  echo "llama-server was not found. Install llama.cpp or set LLAMA_SERVER=/path/to/llama-server"
  exit 1
fi

if [[ -f "$POWER_MODEL" && -f "$POWER_MMPROJ" ]]; then
  MODEL="$POWER_MODEL"; MMPROJ="$POWER_MMPROJ"; ALIAS="imagine-brain"
elif [[ -f "$FAST_MODEL" && -f "$FAST_MMPROJ" ]]; then
  MODEL="$FAST_MODEL"; MMPROJ="$FAST_MMPROJ"; ALIAS="imagine-brain"
else
  echo "No complete Imagine brain model + mmproj pair was found."
  exit 1
fi

exec "$LLAMA_SERVER" -m "$MODEL" --mmproj "$MMPROJ" --alias "$ALIAS" \
  --host 127.0.0.1 --port 8090 -ngl 99 -c 32768 --jinja
