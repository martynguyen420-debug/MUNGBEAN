# GENESIS Imagine

A focused Grok Imagine-style front end for a RunPod ComfyUI installation. The app adds a local Qwen brain that improves prompts and routes requests among the models already installed on the Pod.

## Routes

- `klein_9b` — FLUX.2 Klein 9B image generation
- `aisha_9b` — Aisha 9B realism
- `qwen_edit` — Qwen reference-image editing
- `wan_fast` — Phr00t WAN 2.2 rapid video
- `wan_quality` — WAN 2.2 Remix quality video

## Start on RunPod

```bash
cd /workspace/GENESIS_IMAGINE
chmod +x RUN_ON_RUNPOD.sh START_BRAIN.sh CHECK_BRAIN.sh
./CHECK_BRAIN.sh
./START_BRAIN.sh > /workspace/imagine-brain.log 2>&1 &
./RUN_ON_RUNPOD.sh
```

Open RunPod's HTTP Service for port `7865`. ComfyUI is expected at `127.0.0.1:8188`; the brain API uses `127.0.0.1:8090`.

The brain launcher prefers the 27B model and automatically falls back to the existing 9B model if the complete 27B model/mmproj pair is absent.

## Workflow setup

GENESIS Imagine now supports automatic per-route workflows. Put API-format ComfyUI graphs in `config/workflows/` as `klein_9b.json`, `aisha_9b.json`, `qwen_edit.json`, `wan_fast.json`, or `wan_quality.json`.

The UI selects the matching workflow automatically for the chosen/brain-routed mode. Common prompt, negative, seed, steps, denoise, width, height, image and LoRA inputs are auto-detected. Manual workflow loading remains under **Connection & workflow** as a fallback.

No model weights belong in this repository.
