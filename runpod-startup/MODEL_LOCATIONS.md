# Model file locations

Default ComfyUI root: `/workspace/runpod-slim/ComfyUI`. Set `COMFY_ROOT` explicitly only if your existing installation is elsewhere.

Scripts are `/workspace/1` through `/workspace/6`. Their fetched bundle is cached under `/workspace/.mung-installers`.

| File | Exact default destination |
| --- | --- |
| Qwen-Rapid-NSFW-v23_Q8_0.gguf | `/workspace/runpod-slim/ComfyUI/models/diffusion_models/Qwen-Rapid-NSFW-v23_Q8_0.gguf` |
| Qwen-Rapid-AIO-NSFW-v19_Q8_0.gguf | `/workspace/runpod-slim/ComfyUI/models/diffusion_models/Qwen-Rapid-AIO-NSFW-v19_Q8_0.gguf` |
| Qwen2.5-VL-7B-Instruct-Q8_0.gguf | `/workspace/runpod-slim/ComfyUI/models/text_encoders/Qwen2.5-VL-7B-Instruct-Q8_0.gguf` |
| Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf | `/workspace/runpod-slim/ComfyUI/models/text_encoders/Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf` |
| qwen_image_vae.safetensors | `/workspace/runpod-slim/ComfyUI/models/vae/qwen_image_vae.safetensors` |
| flux-2-klein-9b.safetensors | `/workspace/runpod-slim/ComfyUI/models/diffusion_models/flux-2-klein-9b.safetensors` |
| qwen_3_8b.safetensors | `/workspace/runpod-slim/ComfyUI/models/text_encoders/qwen_3_8b.safetensors` |
| flux2-vae.safetensors | `/workspace/runpod-slim/ComfyUI/models/vae/flux2-vae.safetensors` |
| aisha_nsfw_beta_v9_7_distilled_bf16.safetensors | `/workspace/runpod-slim/ComfyUI/models/diffusion_models/aisha_nsfw_beta_v9_7_distilled_bf16.safetensors` |
| Miraclein NSFW v3.0 FP8 - Klein9B - 12steps,euler,cfg1.1.safetensors | `/workspace/runpod-slim/ComfyUI/models/diffusion_models/Miraclein NSFW v3.0 FP8 - Klein9B - 12steps,euler,cfg1.1.safetensors` |
| KreaNoct_V4_BF16_Civitai3368908.safetensors (manual group 8) | `/workspace/runpod-slim/ComfyUI/models/diffusion_models/KreaNoct_V4_BF16_Civitai3368908.safetensors` |
| KreaNoct_V4_int8_convrot.safetensors | `/workspace/runpod-slim/ComfyUI/models/diffusion_models/KreaNoct_V4_int8_convrot.safetensors` |
| qwen3vl_4b_fp8_scaled.safetensors | `/workspace/runpod-slim/ComfyUI/models/text_encoders/qwen3vl_4b_fp8_scaled.safetensors` |

Custom nodes: `/workspace/runpod-slim/ComfyUI/custom_nodes/ComfyUI-GGUF`.

`paths.json` restricts the installer to ComfyUI native model folders. The lock manifest specifies each exact filename and folder. No extra model-path YAML is needed because ComfyUI already scans these folders.

Whole-model-store symlinks are supported. A category-folder symlink escaping that store is rejected with its path rather than silently downloading elsewhere. Reused verified files can be linked; output shows both the ComfyUI path and actual storage path.

Each installer prints absolute destination paths. The latest run writes `/workspace/.runpod-startup/model-locations.json` and `setup-status.json`. Per-group copies are `group-N-locations.json` and `group-N-status.json`.
