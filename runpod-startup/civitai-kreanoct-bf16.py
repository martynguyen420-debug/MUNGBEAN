#!/usr/bin/env python3
"""Install only Krea Noct V4 BF16, Civitai version 3368908 / file 3257024.

Never edits ComfyUI core, custom nodes, existing models, or either service.
API tokens are read silently and are never saved or passed in URL parameters.
"""
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

MODEL_ID = 2952260
VERSION_ID = 3368908
FILE_ID = 3257024
FILENAME = "KreaNoct_V4_BF16_Civitai3368908.safetensors"
HOSTS = ("https://civitai.com",)  # Only official Civitai: never send API credentials to third parties


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def get_token():
    token = os.environ.get("CIVITAI_TOKEN", "").strip()
    if not token:
        if not sys.stdin.isatty():
            raise RuntimeError("Use a Jupyter TERMINAL and run bash 8 to enter your token privately.")
        token = getpass.getpass("Civitai API token (hidden; not saved): ").strip()
    if not token or any(c in token for c in '\r\n"\\'):
        raise RuntimeError("Missing or invalid Civitai token.")
    return token


def curl(url, output, token, resume=False):
    # Curl excludes Authorization after cross-host CDN redirects by default.
    # The config is sent on stdin, never stored or included in process arguments.
    config = 'header = "Authorization: Bearer ' + token + '"\n'
    cmd = ["curl", "--config", "-", "--fail", "--location",
           "--silent", "--show-error", "--connect-timeout", "30",
           "--speed-limit", "1024", "--speed-time", "120",
           "--retry", "3", "--retry-delay", "5", "--output", str(output)]
    if resume:
        cmd.extend(["--continue-at", "-"])
    cmd.append(url)
    result = subprocess.run(cmd, input=config, text=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode:
        message = (result.stderr or "").strip()
        # Defensive redaction: even unexpected curl error output cannot print the key.
        raise RuntimeError((message or ("curl exit " + str(result.returncode))).replace(token, "[redacted]"))


def load_metadata(token, state):
    errors = []
    for host in HOSTS:
        with tempfile.TemporaryDirectory(prefix="civitai-meta-", dir=state) as tmp:
            target = Path(tmp) / "version.json"
            try:
                curl(host + "/api/v1/model-versions/" + str(VERSION_ID), target, token)
                data = json.loads(target.read_text())
                if data.get("id") != VERSION_ID or data.get("modelId") != MODEL_ID:
                    raise RuntimeError("Civitai returned a different model or version.")
                matches = [f for f in data.get("files", []) if f.get("id") == FILE_ID]
                if len(matches) != 1:
                    raise RuntimeError("Pinned BF16 file ID not present in the Civitai version.")
                item = matches[0]
                name = str(item.get("name", ""))
                if not name.lower().endswith(".safetensors"):
                    raise RuntimeError("Pinned file is not a safetensors model.")
                fmt = str(item.get("metadata", {}).get("format", "SafeTensor")).lower()
                if fmt not in ("safetensor", "safetensors"):
                    raise RuntimeError("Civitai says this file is not SafeTensor.")
                sha = str(item.get("hashes", {}).get("SHA256", "")).lower()
                if not re.fullmatch(r"[0-9a-f]{64}", sha):
                    raise RuntimeError("Civitai has no verifiable SHA256 for this exact file.")
                size = int(float(item.get("sizeKB", 0)) * 1024)
                if size < 16 * 1024 ** 3:
                    raise RuntimeError("Expected BF16-sized file; Civitai reports a smaller variant.")
                print("Verified publisher file:", name, "version", VERSION_ID,
                      "file", FILE_ID, "approx", round(size / 1024 ** 3, 2), "GiB", flush=True)
                return item, sha, size, host
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                errors.append(host + ": " + str(exc).replace(token, "[redacted]"))
    raise RuntimeError("Civitai metadata unavailable or mismatched. " + " | ".join(errors))


def main():
    root = Path(os.environ.get("COMFY_ROOT", "/workspace/runpod-slim/ComfyUI"))
    if not root.is_absolute() or not (root / "main.py").is_file():
        raise RuntimeError("Set COMFY_ROOT to the existing ComfyUI directory.")
    state = Path(os.environ.get("RUNPOD_STATE", "/workspace/.runpod-startup"))
    state.mkdir(parents=True, exist_ok=True)
    dest = root / "models" / "diffusion_models" / FILENAME
    token = get_token()
    _, sha, size, preferred_host = load_metadata(token, state)
    print("Destination:", dest, flush=True)
    if dest.exists():
        if not dest.is_file() or digest(dest) != sha:
            raise RuntimeError("Existing file differs; preserved without overwrite: " + str(dest))
        print("ALREADY PRESENT AND SHA256 VERIFIED:", dest, flush=True)
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    if part.exists() and part.stat().st_size > size + 1024 * 1024:
        raise RuntimeError("Oversized partial file preserved for inspection: " + str(part))
    remain = max(0, size - (part.stat().st_size if part.exists() else 0))
    if shutil.disk_usage(dest.parent).free < remain + 1024 ** 3:
        raise RuntimeError("Not enough free persistent disk space. No files removed.")
    hosts = (preferred_host,) + tuple(h for h in HOSTS if h != preferred_host)
    failures = []
    for host in hosts:
        try:
            url = host + "/api/download/models/" + str(VERSION_ID) + "?fileId=" + str(FILE_ID)
            print("Downloading from official Civitai host:", host, flush=True)
            curl(url, part, token, resume=True)
            if abs(part.stat().st_size - size) > 1024 * 1024:
                raise RuntimeError("Wrong file size; partial preserved.")
            if digest(part) != sha:
                raise RuntimeError("SHA256 mismatch; partial preserved. Do not rename it.")
            os.replace(part, dest)
            print("SUCCESS: SHA256-verified BF16 model saved at", dest, flush=True)
            print("Existing Phr00t GGUF and ComfyUI services were not modified.", flush=True)
            return 0
        except (OSError, RuntimeError) as exc:
            failures.append(host + ": " + str(exc).replace(token, "[redacted]"))
            # Do not try to append a different host's bytes to a nonempty partial.
            if part.exists() and part.stat().st_size:
                break
    raise RuntimeError("Download not completed: " + " | ".join(failures) +
                       ". If access is restricted, use your Civitai account's supported download method.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("KREA BF16:", exc, file=sys.stderr)
        sys.exit(1)
