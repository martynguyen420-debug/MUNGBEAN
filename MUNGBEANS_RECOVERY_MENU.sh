#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${COMFY_ROOT:-}"
if [[ -z "$ROOT" ]]; then
  for p in /workspace/runpod-slim/ComfyUI /workspace/ComfyUI /workspace-global/runpod-slim/ComfyUI; do
    if [[ -f "$p/main.py" ]]; then ROOT="$p"; break; fi
  done
fi
[[ -n "$ROOT" && -f "$ROOT/main.py" ]] || { echo "ComfyUI not found. Set COMFY_ROOT=/actual/path"; exit 1; }
PY="$ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY="$(command -v python3)"
M="$ROOT/models"
mkdir -p "$M"/{diffusion_models,unet,text_encoders,vae,loras,clip_vision,checkpoints} "$ROOT/custom_nodes"

download() {
  local repo="$1" file="$2" folder="$3" type="${4:-model}" base="${2##*/}"
  mkdir -p "$folder"
  [[ ! -s "$folder/$base" ]] || { echo "Already exists: $folder/$base"; return 0; }
  echo "Downloading $repo/$file"
  "$PY" -m pip -q install huggingface_hub
  "$PY" - "$repo" "$file" "$folder" "$type" <<'PY'
import sys, os, shutil, tempfile
from huggingface_hub import hf_hub_download
repo, name, folder, kind = sys.argv[1:]
with tempfile.TemporaryDirectory(dir=folder) as tmp:
    src=hf_hub_download(repo_id=repo, filename=name, repo_type=kind, local_dir=tmp)
    dst=os.path.join(folder,os.path.basename(name))
    if not os.path.exists(dst): shutil.move(src,dst)
    print("Saved:",dst)
PY
}
nodes() {
  local pair url dir
  local items=(
    "https://github.com/ltdrdata/ComfyUI-Manager.git|ComfyUI-Manager"
    "https://github.com/city96/ComfyUI-GGUF.git|ComfyUI-GGUF"
    "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git|ComfyUI-VideoHelperSuite"
    "https://github.com/kijai/ComfyUI-WanVideoWrapper.git|ComfyUI-WanVideoWrapper"
    "https://github.com/rgthree/rgthree-comfy.git|rgthree-comfy"
    "https://github.com/Fannovel16/comfyui_controlnet_aux.git|comfyui_controlnet_aux"
    "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git|ComfyUI-Impact-Pack"
    "https://github.com/kijai/ComfyUI-KJNodes.git|ComfyUI-KJNodes"
  )
  "$PY" -m pip install gguf
  for pair in "${items[@]}"; do
    url="${pair%%|*}"; dir="${pair#*|}"
    if [[ ! -d "$ROOT/custom_nodes/$dir" ]]; then
      git -c http.version=HTTP/1.1 clone --depth 1 "$url" "$ROOT/custom_nodes/$dir" || { echo "Clone failed: $dir"; continue; }
    fi
    [[ ! -f "$ROOT/custom_nodes/$dir/requirements.txt" ]] || "$PY" -m pip install -r "$ROOT/custom_nodes/$dir/requirements.txt" || echo "Requirements failed: $dir"
  done
  echo "Restart ComfyUI after installing nodes."
}
klein() {
  download Comfy-Org/vae-text-encorder-for-flux-klein-9b split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors "$M/text_encoders"
  download Comfy-Org/vae-text-encorder-for-flux-klein-9b split_files/vae/flux2-vae.safetensors "$M/vae"
}
known_model() {
  case "$1" in
    4) klein; download black-forest-labs/FLUX.2-klein-9B flux-2-klein-9b.safetensors "$M/diffusion_models" ;;
    5) klein; download Aisha-AI-Official/flux-2-klein-models aisha_nsfw_beta_v9_7_distilled_bf16.safetensors "$M/diffusion_models" dataset ;;
    8) echo "Krea Noct V4 INT8: source is intentionally not hard-coded until its exact publisher filename is verified." ;;
    *) echo "This entry is listed, but no verified public repository+filename is configured yet. Nothing was downloaded." ;;
  esac
}
verify() {
  echo "ComfyUI: $ROOT | Python: $PY"
  find "$M" -type f -printf '%p (%s bytes)\n' | sort
  find "$ROOT/custom_nodes" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
  df -h "$ROOT"
}
while true; do
  printf '\n=== MUNGBEANS RunPod Setup (14 models) ===\n'
  printf '1. Phr00t Qwen Rapid v19+v23 GGUF Q8\n2. Phr00t v19 AIO\n3. Phr00t v23 AIO\n4. Flux Klein 9B + encoder + VAE\n5. Aisha v9.7 BF16\n6. Miraclein NSFW v3 FP8\n7. WAN 2.2 Remix NSFW\n8. Krea Noct V4 INT8\n9. ERNIE Image Abliterated\n10. CyberRealistic Flux V2.5 FP8\n11. Pony Realism V23\n12. Flux Persephone\n13. BigLustyDonutMix SDXL\n14. Mixture of Perverts SDXL\n15. Install custom nodes\n16. Verify installed models and nodes\n17. Hugging Face login\n0. Exit\n'
  read -rp 'Choose: ' choice || exit 0
  case "$choice" in
    1|2|3|4|5|6|7|8|9|10|11|12|13|14) known_model "$choice" ;;
    15) nodes ;;
    16) verify ;;
    17) "$PY" -m pip install huggingface_hub; hf auth login ;;
    0) exit 0 ;;
    *) echo "Invalid option" ;;
  esac
done
