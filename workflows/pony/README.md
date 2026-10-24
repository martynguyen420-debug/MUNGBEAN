# CyberRealistic Pony v18 CoreShift — ComfyUI

Includes two ComfyUI UI workflows: text-to-image and image-to-image. No custom nodes needed.

Model: cyberdelia/CyberRealisticPony `CyberRealisticPony_V18.0_F16.safetensors` (Pony/SDXL; NOT FLUX). Download into `/workspace/runpod-slim/ComfyUI/models/checkpoints/`.

Use Load Checkpoint (built-in VAE), CLIPSetLastLayer=-2, 32 steps, CFG 5, dpmpp_2m/karras. TXT2IMG uses 896x1152, denoise 1.0. IMG2IMG uses Load Image -> ImageScale -> VAEEncode and denoise 0.55.

Unverified at runtime on user's RunPod. Files are structurally validated UI workflow JSON. Does not touch 8188 or 8189 processes. Link: https://huggingface.co/cyberdelia/CyberRealisticPony
