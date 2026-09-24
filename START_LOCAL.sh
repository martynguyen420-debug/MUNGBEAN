#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export IMAGINE_HOST="${IMAGINE_HOST:-127.0.0.1}"
export IMAGINE_PORT="${IMAGINE_PORT:-7865}"
export COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
URL="http://127.0.0.1:${IMAGINE_PORT}"
if command -v xdg-open >/dev/null 2>&1; then
  (sleep 1; xdg-open "$URL" >/dev/null 2>&1 || true) &
fi
exec python3 server.py
