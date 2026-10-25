# RunPod persistent ComfyUI startup - 22 October 2026

This bundle targets an EXISTING ComfyUI at `/workspace/runpod-slim/ComfyUI`,
with its `.venv-cu128/bin/python` (or the sibling `/workspace/runpod-slim/.venv-cu128`).
It does not install ComfyUI, Python, CUDA or torch on an empty pod. Choose an image
that already provides this installation, or set `COMFY_ROOT` and `COMFY_PYTHON`.
Linux must provide bash, git, curl, flock, tar and python3. Expose 8188 as HTTP.

## Manual Jupyter recovery: installers 1 to 13

For the existing image with `/start.sh`, use `manual-template-start.json` (or the
single line in `manual-template-command.txt`) as the template startup configuration.
It fetches only the scripts, creates `/workspace/1` through `/workspace/13`, then runs
`/start.sh` normally even if fetching fails. No locked model groups install at boot. If CIVITAI_TOKEN is configured, an isolated Krea Noct V4 BF16 download starts automatically without blocking /start.sh.
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
| `bash 8` | **Krea Noct V4 BF16** from Civitai (separate from INT8 group 5; does not touch Phr00t) |
| `bash 9` | ERNIE-Image Abliterated gated encoders + standard ERNIE ComfyUI models |
| `bash 10` | CyberRealistic FLUX.1 v2.5 FP8 + CLIP-L, T5-XXL FP8 and FLUX.1 VAE |
| `bash 11` | BigLustyDonutMix v1.2 SDXL checkpoint, embedded CLIP-L/CLIP-G and VAE |
| `bash 12` | MoP (Mixture of Perverts) v5.1 DMD SDXL checkpoint, embedded CLIP-L/CLIP-G and VAE |
| `bash 13` | PornMaster FLUX.2 Klein V4 Turbo INT8 ConvRot + shared Klein encoder/VAE |

### Number 13: PornMaster V4 Turbo INT8 ConvRot (manual only)

Refresh the numbered installers and run:

```bash
cd /workspace
bash /workspace/MUNGBEAN/runpod-startup/fetch-installers.sh
bash 13
```

This installs `pornmasterFlux2Klein_v4TurboInt8.safetensors` (9,405,866,864 bytes)
into `models/diffusion_models/`, and reuses the pinned
`qwen_3_8b.safetensors` text encoder and `flux2-vae.safetensors` VAE.
These are FLUX.2 Klein 9B support files, **not the Qwen image-edit encoder**.
The model mirror is pinned to
[`Kerstal/f2-klein-9b_model` commit `0acab40`](https://huggingface.co/Kerstal/f2-klein-9b_model/commit/0acab4020afd57452069fa3cb0bf7e79a3d05404)
and the published SHA-256 is checked before installation.

**INT8 loading:** this prequantized checkpoint may need
[ComfyUI-INT8-Fast](https://github.com/BobJohnson24/ComfyUI-INT8-Fast)
and its **Load Diffusion Model INT8 (W8A8)** node, rather than the
stock Load Diffusion Model node, depending on your ComfyUI version and
quantization format support. Install that custom node separately through
ComfyUI Manager if you don't already have it; do not modify PyTorch/CUDA
automatically. Use an existing FLUX.2 Klein 9B workflow with the INT8 loader.

This group is **not** in the auto-start model manifest. Running `bash 13`
won't replace other models or restart ports 8188/8189.
As with other numbered installers, Hugging Face Xet acceleration is enabled
by default; existing valid files are reused.

### Numbers 11 and 12

Refresh the fetch list, then install either model:

```bash
cd /workspace
bash /workspace/MUNGBEAN/runpod-startup/fetch-installers.sh
bash 11
bash 12
```

These optional models are pinned in `sdxl-models.lock.json`, separate from the
automatic startup model set. The existing downloader verifies exact byte counts
and SHA256, reuses matching files, resumes partials and preserves mismatches.
Group model selections and both services are unchanged. No extra custom nodes or separate
encoders/VAE are required: use **Load Checkpoint** in ComfyUI.

- 11: `models/checkpoints/biglustydonutmixNSFW_v12.safetensors` —
  [75dhsx/DonutsDelivery](https://huggingface.co/75dhsx/DonutsDelivery/blob/9ff8cda92d26a4d8175d6e231d7d7328012bc608/biglustydonutmixNSFW_v12.safetensors),
  6,938,462,898 bytes.
- 12: `models/checkpoints/mopMixtureOfPerverts_v51DMD.safetensors` —
  [WPexpertspt/Mixture-of-Perverts-DMD](https://huggingface.co/WPexpertspt/Mixture-of-Perverts-DMD/blob/e9935fd609f32ad4234115a4456e98283d293419/mopMixtureOfPerverts_v51DMD.safetensors),
  6,938,100,234 bytes. This is specifically v5.1 DMD, not v7.1, NO DMD or Illustrious.

Verified on 25 October 2026 using Hugging Face revision/file metadata and small
HTTP range reads of the safetensors headers: both identify SDXL base architecture
and contain the UNet, both text encoders and VAE. These are third-party mirrors;
Civitai's API returned HTTP 451 here, so no live Civitai version claim is made.
Full model payloads were not downloaded for this check; target GPU generation
has not been tested.

### Fast Hugging Face downloads (enabled by default)

New Hugging Face downloads use `huggingface_hub` + `hf_xet`, with
`HF_XET_HIGH_PERFORMANCE=1` unless explicitly overridden. The downloader installs
its own small environment in `/workspace/.runpod-startup/hf-download-venv`;
it does not change ComfyUI, torch or CUDA packages. Exact file sizes and SHA256
are checked before a staged file becomes the installed model.
Existing verified models are reused. Existing nonempty curl `.part` files
continue through curl to preserve their progress. Interrupted Xet transfers
reuse their staging cache. Set `HF_FAST_DOWNLOAD=0` to use the old curl route.
Civitai downloads (group 8) use Civitai's own transfer, not Hugging Face Xet.

The two [importable workflows for 11 and 12](workflows/README.md) are included
with the fetched scripts. Drag the matching JSON into ComfyUI after installing.

### Saved private Civitai key

The account secret is named `MUNG_CIVITAI_TOKEN`. The startup JSON files now
include this environment mapping:

```json
"env": {
  "CIVITAI_TOKEN": "{{ RUNPOD_SECRET_MUNG_CIVITAI_TOKEN }}",
  "HF_XET_HIGH_PERFORMANCE": "1"
}
```

Apply the `env` entries to the RunPod pod/template environment settings as well
as the entrypoint/command when using these configuration files. RunPod resolves
the secret on container startup. A shell script cannot retrieve a write-only
RunPod account secret by itself. Fetching scripts alone does not configure a
pod's environment. Once this mapping is applied, `bash 8` uses the key without
prompting. The actual key is never stored in GitHub.

### Numbers 9 and 10: ERNIE + CyberRealistic FLUX.1

Refresh the existing /workspace numbered Bash commands (no pod restart):

```bash
cd /workspace
bash /workspace/MUNGBEAN/runpod-startup/fetch-installers.sh
bash 9   # ERNIE Abliterated with supporting ComfyUI ERNIE model
bash 10  # CyberRealistic FLUX.1 v2.5 FP8 with matching support files
```

Group 9 requires accepting gated access at
<https://huggingface.co/ponpoke/ERNIE-Image-Abliterated> and authenticating
via a private `HF_TOKEN` environment variable or `hf auth login`.
The access check runs before the large files download. Publisher's
abliterated PE/TE Diffusers components are stored under
`/workspace/ernie-image-abliterated/`; the original ComfyUI ERNIE
model/encoders/VAE are stored in the regular `models/` folders.
**Stock ComfyUI does not automatically load the abliterated Diffusers
components; a compatible conversion/loader is still needed.** Group 9
installs the full original ERNIE model, not Turbo.

Group 10 installs the FP8 **diffusion model** into
`models/diffusion_models/`, its two Flux text encoders into
`models/text_encoders/`, and the FLUX.1 `ae.safetensors` into
`models/vae/`. Both groups use resumable Hugging Face Hub downloads
and the existing process lock; neither touches 8188 or 8189.
Unlike the original SHA-locked groups 1–5, these two new groups are not
yet covered by the `models.lock.json` checks. Do not insert a token
into public GitHub files.

### Number 8: Krea Noct V4 full BF16 from Civitai

Use the refreshed scripts from a **Jupyter Terminal** (not a notebook Python cell):

```bash
cd /workspace
bash /workspace/MUNGBEAN/runpod-startup/fetch-installers.sh
bash 8
```

**Automatic startup (no Jupyter commands):** when the RunPod environment contains
`CIVITAI_TOKEN`, the startup code automatically starts the number 8
BF16 download on the next pod boot, in a separate process so ComfyUI can
start normally. This applies to both the GitHub bootstrap startup and the
existing manual-template startup that fetches `fetch-installers.sh`.
The downloader keeps completed files, verifies their SHA256, and never
touches Phr00t, GGUF nodes or either ComfyUI service. Follow progress in
`/workspace/.runpod-startup/krea-bf16-auto.log`.
Set `AUTO_KREA_BF16=0` in the RunPod environment to opt out.
The one-time `CIVITAI_TOKEN` environment variable must be set privately in
RunPod's pod/template environment settings: do **not** put the token in the
public GitHub repository. If a token was pasted into chat, revoke it and
create a replacement before storing it in RunPod.

For manual downloading, number 8 prompts for your `CIVITAI_TOKEN` without showing the characters.
It does **not** store the token on disk or in GitHub. Alternatively, provide
`CIVITAI_TOKEN` as a RunPod environment secret. Rotate any token previously
pasted into chats or other insecure locations.

The pinned target is Civitai model 2952260, version 3368908, file 3257024,
saved as `models/diffusion_models/KreaNoct_V4_BF16_Civitai3368908.safetensors`.
It checks Civitai's metadata, exact file ID, expected BF16-sized payload and
publisher SHA256 before activating the download. If the Civitai API blocks
access or reports different file metadata, it fails without touching existing
models. The download is one-time and manual; startup automation continues to
use the original locked INT8 version. The Phr00t GGUF loader and files are
never changed. The existing Krea Noct V4 INT8 remains available as group 5.

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

- `CIVITAI_TOKEN`: private Civitai API token used only for the optional automated Krea Noct V4 BF16 download. Never commit to GitHub.
- `AUTO_KREA_BF16`: `1` by default when a Civitai token is present; set `0` to disable the BF16 auto-download.
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

## Klein download mirror - 23 October 2026

Group 2 now downloads the identical Klein 9B BF16 file from ModelsLab/FLUX.2-klein-9B
at pinned revision 04fb1c9d319931d1891a3fa3342c0da4970599e9. Its 18,157,185,168 bytes
and SHA256 match the original BFL file. An anonymous range request succeeded.
The original source is retained in the lock manifest. License terms still apply.
Refresh installers with fetch-installers.sh, then rerun bash 2; shared files are reused.
