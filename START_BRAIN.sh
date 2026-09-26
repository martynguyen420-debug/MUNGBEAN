#!/usr/bin/env bash
set -euo pipefail

POWER_DIR=/workspace/ComfyUI/models/LLM/powerful-brain
FAST_DIR=/workspace/ComfyUI/models/LLM
CTX="${BRAIN_CTX:-32768}"
NGL="${BRAIN_NGL:-99}"

LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || true)}"
if [[ -z "$LLAMA_SERVER" ]]; then
  echo "llama-server was not found. Install llama.cpp or set LLAMA_SERVER=/path/to/llama-server"
  exit 1
fi

pick_first() {
  local pattern
  for pattern in "$@"; do
    shopt -s nullglob
    local hits=( $pattern )
    shopt -u nullglob
    if (( ${#hits[@]} )); then printf '%s\n' "${hits[0]}"; return 0; fi
  done
  return 1
}

MODEL="$(pick_first \
  "$POWER_DIR/Qwen_Qwen3.5-27B-Q4_K_M.gguf" \
  "$POWER_DIR/Qwen3.5-27B-Q4_K_M.gguf" \
  "$POWER_DIR/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf" || true)"
if [[ -z "$MODEL" ]]; then
  MODEL="$(find "$POWER_DIR" -maxdepth 1 -type f -iname '*Qwen*3.5*27B*Q4_K_M*.gguf' ! -iname 'mmproj*' -print -quit 2>/dev/null || true)"
fi

if [[ -n "$MODEL" ]]; then
  MMPROJ="$(pick_first \
    "$POWER_DIR/mmproj-Qwen_Qwen3.5-27B-bf16.gguf" \
    "$POWER_DIR/mmproj-Qwen_Qwen3.5-27B-f16.gguf" \
    "$POWER_DIR/"'mmproj*Qwen*3.5*27B*.gguf' || true)"
  ALIAS="mungbean-qwen3.5-27b"
else
  MODEL="$(pick_first "$FAST_DIR/Qwen3.5-9B-Claude-4.6-OS-AV-H-UNCENSORED-THINK-D_AU-Q4_K_M-imat.gguf" || true)"
  MMPROJ="$(pick_first "$FAST_DIR/mmproj-BF16.gguf" "$FAST_DIR/"'mmproj*9B*.gguf' || true)"
  ALIAS="mungbean-qwen3.5-9b"
fi

if [[ -z "${MODEL:-}" || -z "${MMPROJ:-}" || ! -s "$MODEL" || ! -s "$MMPROJ" ]]; then
  echo "No complete MUNGBEAN brain model + mmproj pair was found."
  echo "Run ./INSTALL_BRAIN_RUNPOD.sh on the RunPod once to install the preferred 27B brain."
  exit 1
fi

echo "MUNGBEAN brain: $ALIAS"
echo "Model: $MODEL"
echo "Vision projector: $MMPROJ"
echo "Context: $CTX"

exec "$LLAMA_SERVER" -m "$MODEL" --mmproj "$MMPROJ" --alias "$ALIAS" \
  --host 127.0.0.1 --port 8090 -ngl "$NGL" -c "$CTX" --jinja
