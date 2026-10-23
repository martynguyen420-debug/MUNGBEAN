# Current MUNGBEAN setup - 22 October 2026

Status: latest prepared attempt. Target RunPod startup and GPU generation are not yet verified.

## Current procedure

- Startup fetches scripts only, then runs the existing image `/start.sh` for Jupyter.
- Paste [the complete single-field start command](runpod-startup/manual-template-command-single-field.txt).
- Separate fields: [manual-template-start.json](runpod-startup/manual-template-start.json).
- In Jupyter Terminal: `cd /workspace`, then `bash 6` for nodes and selected `bash 1` through `bash 5` model groups. Run ash 7 to start missing 8188/8189 services; existing services are preserved.
- [Current PDF](runpod-startup/RUNPOD_MODEL_INSTALL_COMMANDS_2026-10-22.pdf).
- [Exact model folders](runpod-startup/MODEL_LOCATIONS.md), [path safeguards](runpod-startup/paths.json), [model sources and hashes](runpod-startup/models.lock.json).
- [MUNG desktop](mung-desktop) asks for the current pod URL each remote session and validates before saving/switching.

## Checked locally

Shell/Python syntax; five HTTP download fixtures; six MUNG connection regressions; all six installer group selections; twelve explicit model destinations. Model metadata and hashes checked against pinned repository records. These are not live pod/GPU tests.

## Outstanding pod checks

- Image provides `/start.sh` and opens Jupyter.
- ComfyUI root and CUDA Python paths match the installation.
- GGUF nodes import and a real Phr00t generation succeeds.
- Core supports the selected model. KreaNoct requires ComfyUI 0.37 or newer; template screenshot showed 0.30.0. No automatic core/torch/CUDA upgrade.
- Actual 8188 serving and generated outputs. Preserve separate 8189.

Last verified working release of this complete setup: not yet established. Record the exact tested commit and evidence after a successful pod test.

Earlier automatic model-install startup scripts remain alternatives. They are not the current manual-first plan. Start from this page.

## Klein mirror update - 23 October 2026

The official download failed on the pod. Group 2 now uses the ModelsLab mirror,
verified by exact SHA256 and size against the BFL original. Anonymous range download
returned HTTP 206. Full download and GPU generation are still unverified.
