#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
REPO="${STARTUP_REPO:-https://github.com/martynguyen420-debug/MUNGBEAN.git}"
REF="${STARTUP_REF:-main}"
CACHE=/workspace/.runpod-startup-source
mkdir -p "$CACHE"
exec 8>"$CACHE/bootstrap.lock"
flock -n 8 || { echo 'Another GitHub bootstrap is running'; exit 0; }
if [[ ! -d "$CACHE/repo.git" ]]; then git init --bare "$CACHE/repo.git"; fi
ACTIVE="$(readlink -f "$CACHE/current" 2>/dev/null || true)"
prepare_release() {
  git --git-dir="$CACHE/repo.git" fetch --depth=1 "$REPO" "$REF" || return 1
  SHA="$(git --git-dir="$CACHE/repo.git" rev-parse FETCH_HEAD)"
  RELEASE="$CACHE/releases/$SHA"
  if [[ ! -d "$RELEASE" ]]; then
    STAGE="$(mktemp -d "$CACHE/staging.XXXXXX")"
    git --git-dir="$CACHE/repo.git" archive "$SHA" runpod-startup | tar -x -C "$STAGE" || return 1
    bash -n "$STAGE/runpod-startup/runpod-template-start.sh" || return 1
    python3 - "$STAGE/runpod-startup" <<'PY'
import ast,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); ast.parse((p/'setup.py').read_text())
for name in ['models.lock.json','nodes.lock.json']: json.loads((p/name).read_text())
PY
    [[ $? == 0 ]] || return 1
    mkdir -p "$CACHE/releases"
    mv "$STAGE" "$RELEASE"
  fi
  ln -sfn "$RELEASE" "$CACHE/current.next"
  mv -Tf "$CACHE/current.next" "$CACHE/current"
  ACTIVE="$RELEASE"
}
prepare_release || echo 'GitHub fetch or bundle validation failed; using the previously validated cached bundle.'
[[ -n "$ACTIVE" && -s "$ACTIVE/runpod-startup/runpod-template-start.sh" ]] || { echo 'No cached startup bundle. Check GitHub access.'; exit 1; }
# Release bootstrap lock before the long-lived ComfyUI process.
flock -u 8
exec 8>&-
exec bash "$ACTIVE/runpod-startup/runpod-template-start.sh"
