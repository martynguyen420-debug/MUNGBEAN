# MUNGPOD - RunPod ComfyUI add-on

MUNGPOD is a separate RunPod copy of the MUNGON GUI with its own settings. The Windows/local MUNGON folder is untouched.

It runs beside ComfyUI inside a pod, scans that pod's ComfyUI models folders at startup and on Refresh Models, detects model families, and routes each selected model through its compatible workflow. The default ComfyUI API is http://127.0.0.1:8188. Each pod can use its own COMFY_ROOT and therefore discovers that pod's own models. Settings are stored separately in mungpod_settings.json.

The GUI serves on port 7866 by default. Expose HTTP port 7866 in RunPod Connect settings.

## Start

From the cloned repo on the pod:

    cd /workspace/MUNGBEAN/MUNGPOD
    chmod +x START_MUNGPOD.sh
    COMFY_ROOT=/workspace/runpod-slim/ComfyUI COMFY_URL=http://127.0.0.1:8188 ./START_MUNGPOD.sh

Set COMFY_ROOT for that particular pod if its ComfyUI install differs. MUNGPOD also checks common /workspace and /workspace-global roots. For additional model directories, set MUNGPOD_MODEL_ROOTS to a colon-separated list.

Set MUNGPOD_PORT and expose that port to use another GUI port. MUNGPOD_HOST defaults to 0.0.0.0 for the pod proxy.

The launcher creates a dedicated Python environment at /workspace/.mungpod-venv. It does not install GUI packages into ComfyUI's Python environment, download weights, or alter the pod's ComfyUI startup script.
