#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

export MUNGBEAN_MANAGE_BRAIN="${MUNGBEAN_MANAGE_BRAIN:-1}"
export MUNGBEAN_RELEASE_BRAIN="${MUNGBEAN_RELEASE_BRAIN:-1}"
export BRAIN_URL="${BRAIN_URL:-http://127.0.0.1:8090/v1}"

echo "MUNGBEAN is starting on RunPod port 7865"
echo "ComfyUI: 127.0.0.1:8188"
echo "Brain: strongest installed 27B is started on demand and released before generation."
echo "Open the HTTP Service link for port 7865 from your RunPod Connect page."
echo

exec python3 server.py
