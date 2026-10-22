#!/usr/bin/env bash
# Fetch scripts only. No model downloads, package installs or ComfyUI launch.
set -Eeuo pipefail
umask 022
CACHE=/workspace/.mung-installers
REPO="${STARTUP_REPO:-https://github.com/martynguyen420-debug/MUNGBEAN.git}"
REF="${STARTUP_REF:-main}"
mkdir -p "$CACHE"
exec 8>"$CACHE/fetch.lock"
flock -n 8 || { echo 'Installer fetch already running.'; exit 0; }
[[ -d "$CACHE/repo.git" ]] || git init --bare "$CACHE/repo.git"
prepare() {
  git --git-dir="$CACHE/repo.git" fetch --depth=1 "$REPO" "$REF" || return 1
  local sha release stage
  sha="$(git --git-dir="$CACHE/repo.git" rev-parse FETCH_HEAD)"
  release="$CACHE/releases/$sha"
  if [[ ! -d "$release" ]]; then
    stage="$(mktemp -d "$CACHE/staging.XXXXXX")"
    git --git-dir="$CACHE/repo.git" archive "$sha" runpod-startup | tar -x -C "$stage" || return 1
    for file in 1 2 3 4 5 6 install-group.sh; do
      bash -n "$stage/runpod-startup/$file" || return 1
    done
    python3 - "$stage/runpod-startup" <<'PY'
import ast,json,pathlib,sys
p=pathlib.Path(sys.argv[1])
for name in ['setup.py','manual-install.py']: ast.parse((p/name).read_text())
for name in ['models.lock.json','nodes.lock.json','install-groups.json','paths.json']: json.loads((p/name).read_text())
PY
    [[ $? == 0 ]] || return 1
    mkdir -p "$CACHE/releases" || return 1
    mv "$stage" "$release" || return 1
  fi
  ln -sfn "$release" "$CACHE/current.next" || return 1
  mv -Tf "$CACHE/current.next" "$CACHE/current" || return 1
}
prepare || echo 'GitHub fetch failed; keeping cached installers if available.'
[[ -s "$CACHE/current/runpod-startup/manual-install.py" ]] || { echo 'Installers not yet available. Jupyter can still start; retry fetch later.'; exit 1; }
for number in 1 2 3 4 5 6; do
  target="/workspace/$number"
  if [[ -e "$target" ]] && ! grep -q '^# MUNG managed installer wrapper$' "$target"; then
    echo "Keeping existing unrecognized file $target; use the cached installer folder instead."
    continue
  fi
  printf '%s\n' '#!/usr/bin/env bash' '# MUNG managed installer wrapper' \
    "exec bash \"$CACHE/current/runpod-startup/install-group.sh\" $number" > "$target.new"
  mv "$target.new" "$target"
done
echo 'Installers ready in /workspace: bash 6 for nodes; bash 1 through bash 5 for models.'
