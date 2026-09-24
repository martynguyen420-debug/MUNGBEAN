# Automatic workflow routes

Place ComfyUI API-format workflow JSON files here using these exact names:

- klein_9b.json
- aisha_9b.json
- qwen_edit.json
- wan_fast.json
- wan_quality.json

Each file may be either a plain ComfyUI API prompt object or an object with:
- prompt: the ComfyUI API prompt
- _genesis_mapping: optional control mapping

Supported mapping keys:
prompt, negative, seed, steps, denoise, image, width, height

Optional LoRA mapping:
"loras": [
  {"name": "12.inputs.lora_name", "strength": "12.inputs.strength_model"}
]

The UI accepts LoRAs one per line as name|strength.

GENESIS Imagine auto-detects common nodes when the mapping is omitted.
No model weights or remote-service credentials belong here.
