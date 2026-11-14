# mungbeans — current GUI build

**Updated:** 14 November 2026 (AWST)

The current Windows GUI source is `BEAVIS_FIXED.py`, with model workflows and launch scripts under this folder. The matching working copy is `Desktop\mungbeans` on the original Windows machine.

## Verified with ComfyUI 0.45.0 / Intel Arc Pro B60 (14 November)

- **FLUX 3 Klein INT8**: Text-to-Image succeeded at 512×512, 4 steps, CFG 1.0, Euler, simple. ComfyUI reported **34.45 seconds** including cold loading. Output: `mungbeans_FLUX3_00001_.png`.
- **FLUX 3 two-reference Image Edit**: succeeded at 512×512, 4 steps with both reference images provided. Output: `mungbeans_FLUX3_00002_.png`.
- **Krea Noct V4 Q4 GGUF**: Text-to-Image succeeded at 512×512, 4 steps, CFG 1.0, Euler, simple. Output: `KreaMung_00002_.png`.

The GUI now auto-detects Flux 3 diffusion models, uses `qwen3vl_4b_fp8_scaled.safetensors` as its `flux3` text encoder and `flux2-vae.safetensors`, and supports **Image Generate** and **Image Edit with two references**. The Krea workflow is preserved.

**Scope of verification:** These are real ComfyUI API-generated workflows from the current source, not a click-through test of every GUI option or resolution. Other model integrations remain unchanged; they were not retested here. Restart the GUI after applying the update to load the new code.

Run `START_.bat` on the original machine. Change the hard-coded Python path if moved. Local settings, private prompt history, caches, and backups are deliberately excluded from this public repository.

Use this folder, `mungbeans-current`, as the canonical GitHub snapshot for future updates.
