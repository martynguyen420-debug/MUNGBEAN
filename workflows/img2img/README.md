# MUNGBEAN RunPod 8188 — ComfyUI IMG2IMG workflows

Drag one of the four JSON files into ComfyUI. Upload your source image into **Load Image** and adjust the prompt, seed, denoise and ImageScale resolution. They do **not** start/restart ComfyUI or download model weights.

| File | Model | Required companion files |
| --- | --- | --- |
| 01 ERNIE base-compatible | ERNIE Image | `ernie-image.safetensors`, `ministral-3-3b.safetensors`, `flux2-vae.safetensors` |
| 02 CyberRealistic | CyberRealistic FLUX.1 v2.5 FP8 diffusion-only | `clip_l.safetensors`, `t5xxl_fp8_e4m3fn.safetensors`, `ae.safetensors` |
| 03 Krea2 V2.5 | Anything2RealCharacters V2.5 FP8 diffusion model | `qwen3vl_4b_fp8_scaled.safetensors`, `qwen_image_vae.safetensors` |
| 04 Krea2 V3 LoRA | Krea2 Turbo + Anything2RealCharacters V3 LoRA | Same Krea2 encoder/VAE and `krea2_turbo_fp8_scaled.safetensors` |

**ERNIE Abliterated limitation:** The ponpoke release contains Diffusers-format encoder components. Workflow 01 deliberately uses regular ERNIE encoder files; it is **not an abliterated workflow** without a compatible conversion/loader. The image-to-image setup remains experimental.

**Krea requires ComfyUI versions supporting** `TextEncodeQwenImageEditPlus` and `FluxKontextMultiReferenceLatentMethod`. File basenames may need changing in loader dropdowns to match your pod.

**Status:** UI graphs and required links generated and checked; not generation-tested on your actual RunPod. Only tested filenames/nodes on your pod can confirm runtime compatibility. Do not put Civitai or Hugging Face tokens into this public repo.

After `git -C /workspace/MUNGBEAN pull --ff-only`, workflows are in `/workspace/MUNGBEAN/workflows/img2img/`. Your port 8189 is untouched.
