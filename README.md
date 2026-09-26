# GENESIS Imagine / MUNGBEAN

MUNGBEAN is the Grok-Imagine-style image/video director inside GENESIS. It combines a multimodal planning brain with ComfyUI routes for image generation, reference editing and video.

## Start locally

```bash
./START_LOCAL.sh
```

Local mode opens the UI on `http://127.0.0.1:7865` and uses local ComfyUI at `http://127.0.0.1:8188` by default. It does not require or query RunPod unless GENESIS launches it with a remote ComfyUI endpoint.

## Generation routes

- `klein_9b` — FLUX.2 Klein 9B image generation
- `aisha_9b` — Aisha 9B realism
- `qwen_edit` — Qwen reference-image editing
- `wan_fast` — Wan 2.2 fast video route
- `wan_quality` — Wan 2.2 higher-quality video route

The frontend validates every route against the active ComfyUI `/object_info`. MUNGBEAN only routes to workflows whose required nodes and model assets are actually available.

## MUNGBEAN brain

The preferred RunPod brain is **Qwen3.5-27B Q4_K_M with its multimodal projector**. MUNGBEAN queries the brain server's `/v1/models` endpoint instead of assuming a hard-coded model ID.

The director can receive the user's reference image, improve the prompt, preserve the requested intent, choose only backend-runnable routes, and return an execution plan containing route, steps, denoise, reference strategy and optional finishing actions.

On a single 24 GB GPU, MUNGBEAN uses a GPU handoff rather than trying to keep the 27B brain and diffusion models resident together:
1. ComfyUI is asked to unload its loaded models.
2. The 27B brain starts on demand and plans/inspects the reference.
3. The managed brain is released.
4. ComfyUI owns the GPU again for generation.

On larger or multi-GPU systems, set `MUNGBEAN_RELEASE_BRAIN=0` to keep the brain resident.

## First-time RunPod brain install

From the MUNGBEAN directory on the pod:

```bash
chmod +x INSTALL_BRAIN_RUNPOD.sh START_BRAIN.sh CHECK_BRAIN.sh RUN_ON_RUNPOD.sh
./INSTALL_BRAIN_RUNPOD.sh
./CHECK_BRAIN.sh
./RUN_ON_RUNPOD.sh
```

`INSTALL_BRAIN_RUNPOD.sh` installs the preferred Qwen3.5-27B Q4_K_M GGUF and multimodal projector under `/workspace/ComfyUI/models/LLM/powerful-brain`.

`RUN_ON_RUNPOD.sh` enables on-demand brain management automatically. Do not separately start `START_BRAIN.sh` unless you deliberately want a permanently resident brain server.

## Workflow setup

API-format ComfyUI graphs live in `config/workflows/`:
- `klein_9b.json`
- `aisha_9b.json`
- `qwen_edit.json`
- `wan_fast.json`
- `wan_quality.json`

Common prompt, negative prompt, seed, steps, denoise, width, height, image and LoRA inputs are auto-detected. Manual workflow loading remains available under **Connection & workflow** as a fallback.

No model weights belong in this repository.
