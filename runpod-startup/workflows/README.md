# Workflows for installers 13 and 14

Download the JSON and drag it into ComfyUI, or use Workflow > Open.
Run the matching installer first. Both use core nodes only, and load the
checkpoint's embedded CLIP-L, CLIP-G and VAE; no extra downloads are needed.

| Installer | Workflow | Starting settings |
| --- | --- | --- |
| `bash 13` | [BigLustyDonutMix v1.2](11_BigLustyDonutMix_v1_2_TXT2IMG.json) | 30 steps, CFG 2, DPM++ 3M SDE GPU, Karras |
| `bash 14` | [MoP v5.1 DMD](12_MoP_v5_1_DMD_TXT2IMG.json) | 9 steps, CFG 1, LCM, Karras |

Models belong in `COMFY_ROOT/models/checkpoints/`, with the exact filenames
already selected in each Load Checkpoint node. Edit the positive prompt and
resolution to suit. These are minimal text-to-image graphs, using starting
settings from the files' embedded sampling graphs, without their advanced
detailer, merging or upscale stages. No separate LCM LoRA is required for MoP.

Files are also included in the fetched bundle under
`/workspace/.mung-installers/current/runpod-startup/workflows/`.
Graph links, model names, architecture and embedded companion tensors were
checked; generation on the user's GPU has not been tested.
