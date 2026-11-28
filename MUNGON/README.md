# MUNGON - Windows local ComfyUI GUI

Launch `MUNGON.bat`. It uses your installed ComfyUI portable Python and connects to `http://127.0.0.1:8188`.

The source of truth is `MUNGON.py` and its `mungon.css` stylesheet. It includes side-by-side Main and Reference images, a compact row with prompt history, negative prompt, and model-aware steps, and the existing KREA 2 edit grounding pipeline.

A Main Image selects edit/img2img; without one it selects generate. Model selection updates the starting Steps, CFG, Sampler, Scheduler and Denoise. The SDXL checkpoints Mixture of Perverts v5.1 DMD and BigLustyDonutMix v1.2 have separate starting profiles for both modes. These are starting profiles, not individually validated minimums for every model.

For standard upscaling, choose `Standard Model Upscale` from the visible Mode dropdown. The model dropdown scans installed `upscale_models`, including the local 4x-UltraSharp and RealESRGAN_x4plus files, and the scale slider sets the final multiplier. This mode needs no prompt or diffusion steps.

The GUI settings JSON stores private prompt history: do not commit or publish it. The GitHub copy excludes settings, backups, scratch scripts and model weights. ComfyUI itself must be started separately.
