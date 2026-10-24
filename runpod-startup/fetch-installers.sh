#!/usr/bin/env bash
# Fetch scripts. If CIVITAI_TOKEN is configured, also spawn the isolated Krea BF16 installer at boot.
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
    for file in 1 2 3 4 5 6 7 8 9 10 11 12 install-group.sh; do
      bash -n "$stage/runpod-startup/$file" || return 1
    done
    python3 - "$stage/runpod-startup" <<'PY'
import ast,json,pathlib,sys
p=pathlib.Path(sys.argv[1])
for name in ['setup.py','manual-install.py','start-two-ports.py','civitai-kreanoct-bf16.py','download-extra-models.py']: ast.parse((p/name).read_text())
for name in ['models.lock.json','sdxl-models.lock.json','nodes.lock.json','install-groups.json','paths.json']: json.loads((p/name).read_text())
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
for number in 1 2 3 4 5 6 7 8 9 10 11 12; do
  target="/workspace/$number"
  if [[ -e "$target" ]] && ! grep -q '^# MUNG managed installer wrapper$' "$target"; then
    echo "Keeping existing unrecognized file $target; use the cached installer folder instead."
    continue
  fi
  printf '%s\n' '#!/usr/bin/env bash' '# MUNG managed installer wrapper' \
    "exec bash \"$CACHE/current/runpod-startup/install-group.sh\" $number" > "$target.new"
  mv "$target.new" "$target"
done
echo 'Ready in /workspace: bash 6 nodes; bash 1 through bash 5 models; bash 7 starts both ComfyUI ports; bash 8 installs Krea Noct V4 BF16 from Civitai; bash 9 installs ERNIE Abliterated; bash 10 installs CyberRealistic FLUX.1 v2.5; bash 11 installs BigLustyDonutMix v1.2; bash 12 installs MoP v5.1 DMD.'

# The normal RunPod template calls this fetcher before /start.sh.
# When a private token is provided, start the optional BF16 download outside
# the bootstrap timeout; do NOT delay ComfyUI or modify any GGUF models.
if [[ -n "${CIVITAI_TOKEN:-}" && "${AUTO_KREA_BF16:-1}" != "0" ]]; then
  export RUNPOD_STATE="${RUNPOD_STATE:-/workspace/.runpod-startup}"
  export MUNG_KREA_GROUP="$CACHE/current/runpod-startup/install-group.sh"
  mkdir -p "$RUNPOD_STATE"
  flock -u 8
  exec 8>&-
  if command -v setsid >/dev/null 2>&1; then
    setsid -f bash -c '
      exec 7>"$RUNPOD_STATE/krea-bf16-auto.lock"
      flock -n 7 || exit 0
      exec bash "$MUNG_KREA_GROUP" 8
    ' >>"$RUNPOD_STATE/krea-bf16-auto.log" 2>&1 </dev/null
    echo 'Krea Noct BF16 auto-download launched; status: /workspace/.runpod-startup/krea-bf16-auto.log'
  else
    echo 'setsid unavailable; Krea BF16 auto-download skipped safely.'
  fi
else
  echo 'Krea Noct BF16 auto-download skipped (CIVITAI_TOKEN not configured or disabled).'
fi
