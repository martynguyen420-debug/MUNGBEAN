# RunPod persistent ComfyUI startup - 22 October 2026

This bundle targets an EXISTING ComfyUI at `/workspace/runpod-slim/ComfyUI`,
with its `.venv-cu128/bin/python` (or the sibling `/workspace/runpod-slim/.venv-cu128`).
It does not install ComfyUI, Python, CUDA or torch on an empty pod. Choose an image
that already provides this installation, or set `COMFY_ROOT` and `COMFY_PYTHON`.
Linux must provide bash, git, curl, flock, tar and python3. Expose 8188 as HTTP.

## Manual Jupyter recovery: installers 1 to 7

For the existing image with `/start.sh`, use `manual-template-start.json` (or the
single line in `manual-template-command.txt`) as the template startup configuration.
It fetches only the scripts, creates `/workspace/1` through `/workspace/6`, then runs
`/start.sh` normally even if fetching fails. No models or packages install at boot.
Fetches have a 180-second limit and keep a cached copy for later launches.

In Jupyter terminal, run `cd /workspace`, then `bash 6` or a model number. These
numbered scripts install only the selected group and never start, stop or restart
either ComfyUI port. Download the scripts once in Jupyter's terminal:

```bash
git clone https://github.com/martynguyen420-debug/MUNGBEAN.git /workspace/MUNGBEAN
cd /workspace/MUNGBEAN/runpod-startup
```

If this checkout already exists, update it using
`git -C /workspace/MUNGBEAN pull --ff-only`, then enter the same folder.

| Type | Installs |
| --- | --- |
| `bash 1` | Phr00t v19 + v23 Q8 GGUF, Qwen encoder, mmproj and VAE |
| `bash 2` | Klein 9B, Qwen3 8B encoder and Flux2 VAE |
| `bash 3` | Miraclein v3 FP8 and shared encoder/VAE |
| `bash 4` | Aisha v9.7 BF16 and shared encoder/VAE |
| `bash 5` | KreaNoct V4 INT8 ConvRot, encoder and VAE |
| `bash 6` | Custom nodes: the pinned ComfyUI-GGUF loader and missing dependencies |

Run `bash 6` first for GGUF workflows. Choose only the model groups you want.
Each group reuses the same verified model files, receipts, resumed partials and
startup lock. Standalone groups 3 and 4 also include their shared support files,
so installing Klein first is optional. Per-group results are saved to
`/workspace/.runpod-startup/group-N-status.json`. Start 8188 through your existing
ComfyUI launcher after installation. Restart only that service if it was running
when nodes were installed. The automatic GitHub startup path below still installs
the complete model set on launch; use the normal image/Jupyter entrypoint for
manual-only operation.

## GitHub startup

Repository: https://github.com/martynguyen420-debug/MUNGBEAN/tree/main/runpod-startup

Use `template-start.json` as the container entrypoint/command configuration. If the
RunPod UI presents separate fields, set Entrypoint to `/bin/bash -c`, then paste
the single line from `template-command.txt` into Command. This fetches the bootstrap
from GitHub; no file upload from C: is needed. On a first boot internet access is
required. Later boots fall back to the cached bootstrap and bundle if GitHub fails.
The repository is trusted executable startup code. Default `STARTUP_REF=main`
adopts committed changes each launch. Set it to an approved full commit SHA to pin.

For a one-time terminal launch, run:

```bash
curl -fLsS --retry 3 \
  https://raw.githubusercontent.com/martynguyen420-debug/MUNGBEAN/main/runpod-startup/github-bootstrap.sh \
  -o /workspace/runpod-template-bootstrap.sh
bash /workspace/runpod-template-bootstrap.sh
```

Run that only when 8188 is stopped through its existing launcher; an occupied 8188
causes a clear exit. No process is killed. The existing 8189 service is not managed.
Replacing the image entrypoint means this bundle starts ComfyUI only; it does not
start Jupyter or other image services. Keep the image's service supervisor if those
are needed and arrange for it to invoke this bootstrap as its 8188 service.

## Environment settings

Set these in the RunPod template/pod environment, not in GitHub:

- `HF_TOKEN`: optional Hugging Face read token. Accept the official Klein 9B license
  with the same account before downloading. Unauthorized/gated files fail individually;
  partial files persist and available ComfyUI still launches.
- `COMFY_ROOT`: default `/workspace/runpod-slim/ComfyUI`.
- `COMFY_PYTHON`: optional explicit existing environment Python path.
- `COMFY_INSTANCE_DIR`: default `/workspace/comfy8188`, separate user/input/output/temp
  and database directories. Set this to your existing 8188 instance directory if you
  want its existing workflows/settings. Never point it at the running 8189 instance.
- `STARTUP_REF`: default `main`; optionally a full reviewed Git commit SHA.
- `VERIFY_ALL=1`: rehash all installed model bytes once on this launch.

## Model set

The lock manifest contains 12 files, 134,053,727,466 bytes (124.85 GiB), plus ComfyUI
and outputs. Allow at least 150 GB FREE for these assets and leave extra output space.
Use a persistent volume large enough for the installation and generations. A new GPU
can reuse models only when it mounts the same persistent files at the expected paths.
Volume and GPU data-center compatibility still applies.

| Model | Encoder | VAE / loader |
| --- | --- | --- |
| Phr00t Rapid v19 + v23 Q8_0 GGUF (Novice25 quantization) | Qwen2.5-VL 7B Q8_0 GGUF + matching BF16 mmproj | Qwen Image VAE; UnetLoaderGGUF + CLIPLoaderGGUF type qwen_image |
| Official FLUX.2 Klein 9B distilled BF16 | Qwen3 8B BF16 | Flux2 VAE; UNETLoader + CLIPLoader type flux2 |
| Miraclein NSFW v3.0 FP8 9B | shared Qwen3 8B | shared Flux2 VAE; UNETLoader, not checkpoint loader |
| Aisha NSFW beta v9.7 distilled BF16 | shared Qwen3 8B | shared Flux2 VAE; UNETLoader |
| KreaNoct V4 INT8 ConvRot | Qwen3-VL 4B FP8 scaled | shared Qwen Image VAE; core diffusion-model loader |

The mmproj filename is `Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf`, beside the
Qwen2.5-VL encoder. The pinned GGUF loader strips the quantization suffix to match it.
KreaNoct's publisher specifies ComfyUI >=0.37, 8 steps, CFG 1, euler/simple.
Phr00t v23 recommends euler_ancestral/beta, CFG 1 and 4-8 steps. Miraclein's mirror
filename suggests 12 steps/euler/CFG 1.1; this is mirror guidance, not a GPU-validated
workflow. Use the official Klein distilled workflow for Klein and a matching
publisher workflow for Aisha. KreaNoct uses core nodes, not the GGUF loader.

Only ComfyUI-GGUF is installed. It is the minimal node from the recovered
`install_custom_nodes.sh`. Existing other nodes are preserved. The older two-port
script also listed video/rgthree nodes; these are not needed for this image-model set.

## Persistent behavior and package protection

- A lock prevents concurrent startup/download runs. Completed files are checked by
  exact byte count and SHA256 before reuse. A fingerprint receipt avoids hashing
  unchanged multi-GB files on every launch. `VERIFY_ALL=1` forces a new full hash pass.
- Exact matching basenames elsewhere under this ComfyUI `models` tree are hashed
  and symlinked instead of copied. External model stores are not automatically scanned.
- Downloads resume through `.part` files. Only matching size AND SHA256 allows rename
  to the final model filename. Existing mismatching files and bad partials are kept
  for inspection; they are not automatically replaced with repeated new downloads.
- Every missing remote path is checked at its locked HF revision against the stored
  size/hash before the download phase. An inaccessible file does not block other files.
- There are no automatic core, torch, CUDA or existing package updates. A new GGUF
  checkout is pinned. Only missing gguf/sentencepiece/protobuf packages are installed
  with exact versions and `--no-deps`. An existing node at a different commit is
  preserved and reported. Existing dependencies still need to be compatible.
- Core source must contain Klein/Qwen/Krea2 support before automatic model setup.
  An older core is reported and preserved, rather than upgraded on every boot.
- Port 8188 starts after setup, including individual download failures. First boot
  may take a long time; watch logs. Port 8189 is never killed, relaunched or rebound.

## Check serving and model readiness

```bash
tail -n 100 /workspace/.runpod-startup/startup.log
cat /workspace/.runpod-startup/setup-status.json
curl --connect-timeout 5 --max-time 15 -fsS \
  http://127.0.0.1:8188/system_stats
curl --connect-timeout 5 --max-time 15 -fsS \
  http://127.0.0.1:8188/object_info/UnetLoaderGGUF
curl --connect-timeout 5 --max-time 15 -fsS \
  http://127.0.0.1:8188/object_info/CLIPLoaderGGUF
```

Then open the RunPod 8188 proxy URL and generate one small image with each intended
workflow. A 200 response and file hashes do not prove GPU generation compatibility.
Local validation covered Bash syntax and five real HTTP downloader fixtures:
completed reuse, range resume, corrupt partial preservation, corrupt-existing
rejection and HTTP 403 handling. No target Linux/GPU generation test has been run.

If a final file or full partial fails hashing, inspect it and compare with the
manifest before manually moving it aside. A short partial can be resumed on the
next normal launch. Do not run the setup helper directly while another launch owns
the startup lock. To recheck every file, set `VERIFY_ALL=1` for the next normal launch,
then remove that setting when finished. Never use the old two-port kill script for
routine 8188 startup.

## Verification sources

- https://huggingface.co/Novice25/Qwen-Image-Edit-Rapid-AIO-GGUF
- https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO
- https://huggingface.co/unsloth/Qwen2.5-VL-7B-Instruct-GGUF
- https://huggingface.co/QuantStack/Qwen-Image-Edit-GGUF
- https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI
- https://huggingface.co/black-forest-labs/FLUX.2-klein-9B
- https://huggingface.co/Comfy-Org/flux2-klein-9B
- https://huggingface.co/EllaPriest45/Klein9B_Checkpoints (third-party Civitai backup)
- https://huggingface.co/datasets/Aisha-AI-Official/flux-2-klein-models
- https://huggingface.co/Noctaluna/Krea2-Noct-Uncensored
- https://huggingface.co/Comfy-Org/Krea-2
- https://github.com/city96/ComfyUI-GGUF

The exact files/revisions, byte counts and all SHA256 values are in `models.lock.json`.
Metadata and relevant tensor headers were checked on 22 October 2026. This verifies
file identity and architectural pairing, not authorship of third-party mirror files
or successful inference on a particular GPU.

## Exact download folders

See `MODEL_LOCATIONS.md` for every complete default destination. `paths.json`
restricts destinations to native ComfyUI model folders. Installers reject unsafe or
unrecognized paths and print absolute saved/reused locations. No extra YAML is
needed for files installed in these standard folders. Per-group location/status
reports are saved under `/workspace/.runpod-startup`.

## Two-port launcher

Run ash 7 after your chosen installations. It uses separate directories at
/workspace/comfy8188 and /workspace/comfy8189 for new services; existing running
services and their directories are preserved. Set COMFY_INSTANCE_8188 and
COMFY_INSTANCE_8189 to reuse explicit existing instance directories. Both must
be exposed as HTTP ports in RunPod. Both services share models and GPU capacity.
Four mocked launcher tests passed; real two-port GPU operation is not yet verified.
