#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "GENESIS Imagine is starting on RunPod port 7865"
echo "Open the HTTP Service link for port 7865 from your RunPod Connect page."
echo "The GUI will automatically connect to this Pod's port 8188."
echo

exec python3 server.py
