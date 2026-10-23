#!/usr/bin/env python3
"""Optional RunPod installers 9/10; do not alter ComfyUI or other model groups."""
import os
import sys
from pathlib import Path

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    sys.exit("huggingface_hub is missing in COMFY_PYTHON. Install just that package in the existing ComfyUI environment, then retry.")

ROOT = Path(os.environ.get("COMFY_ROOT", "/workspace/runpod-slim/ComfyUI"))
MODELS = ROOT / "models"
EXTRAS = Path(os.environ.get("ERNIE_ABLITERATED_DIR", "/workspace/ernie-image-abliterated"))
TOKEN = os.environ.get("HF_TOKEN") or None
GROUP = sys.argv[1] if len(sys.argv) > 1 else ""
if GROUP not in {"9", "10"}:
    sys.exit("Choose downloader 9 or 10.")
if not (ROOT / "main.py").is_file():
    sys.exit(f"Existing ComfyUI missing: {ROOT}")

def fetch(repo, source_file, local_dir, minimum_size=1):
    local_dir = Path(local_dir)
    target = local_dir / source_file
    local_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nDownloading/validating {repo}/{source_file}\n -> {target}", flush=True)
    try:
        # The Hub client resumes interrupted downloads with local-dir metadata.
        result = Path(hf_hub_download(repo_id=repo, filename=source_file,
                                      local_dir=str(local_dir), token=TOKEN))
    except Exception as error:
        print(f"DOWNLOAD FAILED: {repo}/{source_file}: {error}", file=sys.stderr)
        raise
    if not result.is_file() or result.stat().st_size < minimum_size:
        raise RuntimeError(f"Missing or suspiciously small model: {result}")
    print(f"OK {result} ({result.stat().st_size:,} bytes)", flush=True)

if GROUP == "9":
    print("9: ERNIE Image Abliterated + ComfyUI ERNIE support models", flush=True)
    print("Abliterated weights are gated: first accept access at https://huggingface.co/ponpoke/ERNIE-Image-Abliterated and set HF_TOKEN or use hf auth login.", flush=True)
    # Access check BEFORE any multi-GB model transfers.
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_url
        get_hf_file_metadata(
            hf_hub_url("ponpoke/ERNIE-Image-Abliterated", "abliterated_pe/model.safetensors"),
            token=TOKEN,
        )
    except Exception as error:
        sys.exit(f"ERNIE abliterated access not yet granted (no downloads started): {error}")
    # Publisher's exact Diffusers components, kept separate; not incorrectly
    # presented as drop-in ComfyUI single-file encoders.
    for filename in [
        "abliterated_pe/config.json",
        "abliterated_pe/generation_config.json",
        "abliterated_pe/chat_template.jinja",
        "abliterated_pe/tokenizer.json",
        "abliterated_pe/tokenizer_config.json",
        "abliterated_pe/model.safetensors",
        "abliterated_text_encoder/config.json",
        "abliterated_text_encoder/tokenizer.json",
        "abliterated_text_encoder/tokenizer_config.json",
        "abliterated_text_encoder/model.safetensors",
    ]:
        fetch("ponpoke/ERNIE-Image-Abliterated", filename, EXTRAS,
              100_000_000 if filename.endswith("model.safetensors") else 1)
    # Stock ComfyUI repack. Used until an abliterated encoder conversion /
    # compatible loader is validated; no existing encoder is overwritten.
    for filename in [
        "diffusion_models/ernie-image.safetensors",
        "text_encoders/ministral-3-3b.safetensors",
        "text_encoders/ernie-image-prompt-enhancer.safetensors",
        "vae/flux2-vae.safetensors",
    ]:
        fetch("Comfy-Org/ERNIE-Image", filename, MODELS, 100_000_000)
    print("\nERNIE stock ComfyUI assets installed; abliterated Diffusers encoders at " + str(EXTRAS), flush=True)
    print("Abliterated encoders require an adapted loader/conversion for ComfyUI; simply downloading them does NOT enable them in stock ComfyUI.", flush=True)

elif GROUP == "10":
    print("10: CyberRealistic FLUX.1 v2.5 FP8 + CLIP-L, T5-XXL FP8 and FLUX.1 VAE", flush=True)
    fetch("cyberdelia/CyberRealisticFlux",
          "CyberRealistic_Flux_V2.5_FP8.safetensors",
          MODELS / "diffusion_models", 1_000_000_000)
    for filename in ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"]:
        fetch("comfyanonymous/flux_text_encoders", filename,
              MODELS / "text_encoders", 100_000_000)
    # Public mirror containing the standard FLUX.1 AE, same reported
    # content checksum as the upstream FLUX.1 autoencoder.
    fetch("flux-safetensors/flux-safetensors",
          "ae.safetensors", MODELS / "vae", 100_000_000)
    print("\nCyberRealistic FLUX.1 v2.5 FP8 support bundle installed.", flush=True)

print("Both ComfyUI ports were left unchanged.", flush=True)
