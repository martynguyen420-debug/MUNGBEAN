# GENESIS Imagine

A focused Grok Imagine-style front end for ComfyUI. The app adds an optional local Qwen brain that improves prompts and routes requests among configured image/video workflows.

## Start locally

```bash
./START_LOCAL.sh
```

This opens the UI on `http://127.0.0.1:7865` and uses local ComfyUI at `http://127.0.0.1:8188` by default. The local launcher does not require or query RunPod.

## Routes

- `klein_9b` — FLUX.2 Klein 9B image generation
- `aisha_9b` — Aisha 9B realism
- `qwen_edit` — Qwen reference-image editing
- `wan_fast` — Wan 2.2 fast 4-step video workflow with LightX2V acceleration
- `wan_quality` — Wan 2.2 quality 20-step high/low-noise workflow without LightX2V acceleration

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

When ComfyUI is online, the UI also checks `/object_info` for every route. A route is only treated as backend-ready when all required node classes and referenced model/LoRA filenames are offered by that ComfyUI instance. Missing routes are disabled with the missing nodes/models shown in the button tooltip.

No model weights belong in this repository.
