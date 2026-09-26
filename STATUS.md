# Status — 2026-09-26

## MUNGBEAN brain/director pass

- MUNGBEAN remains the Grok-style image/video workspace inside GENESIS.
- Preferred practical RunPod brain is Qwen3.5-27B Q4_K_M with a multimodal projector.
- Brain model ID is discovered from the live OpenAI-compatible `/v1/models` endpoint.
- Reference images can be sent to the brain as multimodal input for planning.
- The brain receives the exact list of routes proven runnable on the current ComfyUI backend.
- Manual route selection is preserved; the brain cannot silently switch to an unavailable route.
- Plans include intent, reference strategy and optional finishing actions in addition to route/prompt/settings.
- Stale brain plans are invalidated when prompt, negative prompt, mode or reference changes.
- UI shows the active brain model and the planned route/finishing strategy.

## Single-GPU RunPod handoff

- `RUN_ON_RUNPOD.sh` enables managed-brain mode.
- Before loading the 27B brain, MUNGBEAN asks ComfyUI to unload loaded models.
- The brain is started only when planning is needed.
- A brain process started by MUNGBEAN is released after planning so ComfyUI can reclaim the GPU.
- MUNGBEAN never terminates an independently started brain process.
- `MUNGBEAN_RELEASE_BRAIN=0` keeps a managed brain resident for larger/multi-GPU systems.

## Brain deployment files

- `INSTALL_BRAIN_RUNPOD.sh` — installs the preferred 27B GGUF and multimodal projector.
- `CHECK_BRAIN.sh` — inventories the model pair and checks the brain API.
- `START_BRAIN.sh` — prefers the 27B pair and falls back to the existing 9B pair if necessary.
- `RUN_ON_RUNPOD.sh` — starts MUNGBEAN with on-demand GPU handoff enabled.

## Existing generation routes

- Klein 9B
- Aisha 9B
- Qwen Edit / reference editing
- WAN Fast
- WAN Quality

Every route continues to be checked against ComfyUI `/object_info` for required nodes and model filenames before it can run.

## Verification completed locally

- Python syntax checks pass.
- Shell syntax checks pass for all brain/launcher scripts.
- Browser JavaScript syntax check passes.
- MUNGBEAN integration suite passes: 4 tests.
- Tests cover brain model discovery, route planning, multimodal reference input, ComfyUI proxying and workflow registry.
- No GPU-heavy inference job was started during this verification.

## Still blocked on live RunPod deployment

The current RunPod MCP connection in Codex is configured but still reports **Not logged in**. Therefore this pass did not install the 27B weights onto the live pod or start/stop RunPod resources.

Once RunPod authorization succeeds, the next live steps are:
1. identify the correct GENESIS/MUNGBEAN pod;
2. sync this MUNGBEAN build;
3. run `INSTALL_BRAIN_RUNPOD.sh`;
4. run `CHECK_BRAIN.sh`;
5. start MUNGBEAN on port 7865;
6. verify one real brain-planned generation end to end.
