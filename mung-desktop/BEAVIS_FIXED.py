"""
Universal ComfyUI GUI — RunPod Edition

Designed for the user's Windows ComfyUI setup.

Requirements:
    pip install gradio requests pillow

Main features:
- Scans multiple ComfyUI model roots (checkpoints, UNET/diffusion, CLIP/text encoders,
  VAE, LoRA, upscale models) and ignores recycle/trash folders.
- Flux.2 Klein image edit + text-to-image generation.
- Optional second reference image for Flux.2 Klein.
- Qwen Rapid image edit using TextEncodeQwenImageEditPlus with real positive + negative conditioning.
- FLUX.2 Klein optional ConditioningZeroOut negative mode (default ON).
- Standard checkpoint generation and img2img (SDXL/Pony/SD1.5 compatible).
- Ultimate SD Upscale mode (when the custom node is installed).
- LoRA ON/OFF + dropdown + strength. Uses model-only LoRA loading for separated
  diffusion-model pipelines and normal model+CLIP LoRA loading for checkpoints.
- Text encoder presets for Klein: Auto / Official / Uncensored / Custom.
  GGUF text encoders automatically use CLIPLoaderGGUF when installed.
- Source-resolution toggle, manual presets, preserve-source-aspect-ratio option.
- Sampler/scheduler controls and per-model recommendations + saved notes.
- ComfyUI status, interrupt/cancel, output-folder button.
- Configurable ComfyUI launch flags with Auto-FP8 behavior and safe restart of only
  the ComfyUI process launched by this GUI.

Notes:
- "Universal" means the GUI routes different model families through compatible
  pipelines. It does NOT force incompatible checkpoints through a Flux workflow.
- ComfyUI must already know about the external model roots (e.g. via extra_model_paths.yaml)
  for a file found by this scanner to be loadable by ComfyUI.
"""

from __future__ import annotations

import io
import json
import os
import random
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr
import requests
from PIL import Image
import socket

# ============================================================================
# CONFIG
# ============================================================================

APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "universal_comfy_gui_runpod_settings.json"
COMFY_URL = "http://127.0.0.1:8188"

# Default portable install inferred from the user's machine screenshots/setup.
DEFAULT_COMFY_ROOT = Path(r"C:\ai\ComfyUI_windows_portable_b580")
DEFAULT_COMFY_MAIN = DEFAULT_COMFY_ROOT / "ComfyUI" / "main.py"
DEFAULT_COMFY_PYTHON = DEFAULT_COMFY_ROOT / "python_embeded" / "python.exe"
DEFAULT_COMFY_OUTPUT = DEFAULT_COMFY_ROOT / "ComfyUI" / "output"

MODEL_ROOTS = [
    Path(r"C:\ai\ComfyUI_windows_portable_b580\ComfyUI\models"),
    Path(r"C:\ai\AI Playground\resources\models\ComfyUI"),
    Path(r"D:\ai\models\ComfyUI"),
    Path(r"D:\AI-Models"),
    Path(r"D:\AI_Models"),
    Path(r"D:\models"),
]

# Extra loose LoRA locations found on the user's machine.
EXTRA_LORA_DIRS = [
    Path(r"D:\ttf"),
]

EXCLUDED_DIR_NAMES = {
    "$recycle.bin",
    ".trash-1000",
    "system volume information",
    ".git",
    "__pycache__",
}

MODEL_EXTS = (".safetensors", ".gguf", ".sft", ".ckpt", ".pt", ".pth")

RES_PRESETS = {
    "Custom": None,
    "512 × 512": (512, 512),
    "768 × 768": (768, 768),
    "1024 × 1024": (1024, 1024),
    "1280 × 720 (HD)": (1280, 720),
    "1920 × 1080 (FHD)": (1920, 1080),
    "2560 x 1440 (QHD)": (2560, 1440),
    "1440 x 2560 (Portrait)": (1440, 2560),
    "2048 x 2048": (2048, 2048),
    "3840 x 2160 (4K)": (3840, 2160),
    "2160 x 3840 (Portrait 4K)": (2160, 3840),
    "832 × 1216 (Portrait)": (832, 1216),
    "1216 × 832 (Landscape)": (1216, 832),
}

MODES = [
    "Auto",
    "FLUX.2 Klein - Image Edit",
    "FLUX.2 Klein - Image Generate",
    "Qwen Rapid - Image Edit",
    "Checkpoint - Generate",
    "Checkpoint - Img2Img",
    "Standard Model Upscale",
    "Ultimate SD Upscale",
]

FAMILY_OVERRIDES = ["Auto", "FLUX.2 Klein", "Qwen Rapid", "SDXL / Pony", "SD1.5", "Checkpoint / Unknown"]

SAMPLERS = [
    "euler", "euler_ancestral", "heun", "lms", "dpm_2", "dpm_2_ancestral",
    "dpmpp_2s_ancestral", "dpmpp_2m", "dpmpp_sde", "dpmpp_2m_sde",
]
SCHEDULERS = ["normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform", "beta"]
SCALE_METHODS = ["lanczos", "bicubic", "bilinear", "nearest-exact", "area"]

_current_prompt_id: Optional[str] = None
_cancel_requested = False
_owned_comfy_process: Optional[subprocess.Popen] = None
_comfy_log: deque[str] = deque(maxlen=250)
_object_info_cache: Optional[Dict[str, Any]] = None


# ============================================================================
# SETTINGS / NOTES
# ============================================================================

def default_settings() -> Dict[str, Any]:
    return {
        "comfy_url": COMFY_URL,
        "model_source": "local",
        "comfy_python": str(DEFAULT_COMFY_PYTHON),
        "comfy_main": str(DEFAULT_COMFY_MAIN),
        "comfy_output": str(DEFAULT_COMFY_OUTPUT),
        "windows_standalone": True,
        "preview_none": True,
        "fast_disk": True,
        "auto_fp8": True,
        "fp8_unet": False,
        "fp8_text": False,
        "extra_args": "",
        "last_mode": "Auto",
        "last_family_override": "Auto",
        "prompt_history": [],
        "model_notes": {},
    }


def load_settings() -> Dict[str, Any]:
    data = default_settings()
    try:
        if SETTINGS_FILE.is_file():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update(saved)
    except Exception:
        pass
    return data


def save_settings_dict(data: Dict[str, Any]) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _comfy_log.append(f"Could not save settings: {e}")


def startup_connection(settings: Dict[str, Any]) -> Tuple[str, str]:
    # Pod addresses can belong to a stopped/replaced pod. Never restore a saved
    # remote address as an active connection; require this session's explicit URL.
    if str(settings.get("model_source", "local")) == "remote":
        return "", "remote"
    return "http://127.0.0.1:8188", "local"


SETTINGS = load_settings()
COMFY_URL, MODEL_SOURCE = startup_connection(SETTINGS)
_runpod_needs_connection = MODEL_SOURCE == "remote" and not COMFY_URL
_prompt_history = deque(SETTINGS.get("prompt_history", []), maxlen=5)


# ============================================================================
# MODEL SCANNING
# ============================================================================

def _walk_model_folder(folder: Path) -> List[str]:
    if not folder.is_dir():
        return []
    found: List[str] = []
    try:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [
                d for d in dirs
                if d.casefold() not in EXCLUDED_DIR_NAMES
                and not d.casefold().startswith("$recycle")
            ]
            for name in files:
                if name.casefold().endswith(MODEL_EXTS):
                    rel = os.path.relpath(os.path.join(root, name), folder)
                    found.append(rel.replace("/", "\\"))
    except (PermissionError, OSError):
        pass
    return sorted(set(found), key=str.casefold)


def _encode_choice(category: str, rel: str, root_index: int) -> str:
    return json.dumps({"category": category, "rel": rel, "root": root_index}, separators=(",", ":"))


def _decode_choice(value: Optional[str]) -> Tuple[str, str, int]:
    if not value:
        return "", "", -1
    try:
        obj = json.loads(value)
        return str(obj.get("category", "")), str(obj.get("rel", "")), int(obj.get("root", -1))
    except Exception:
        return "", str(value), -1


def scan_all_models() -> Dict[str, List[Tuple[str, str]]]:
    buckets: Dict[str, List[Tuple[str, str]]] = {
        "models": [], "clips": [], "vaes": [], "loras": [], "upscalers": [], "controlnets": []
    }
    category_map = {
        "checkpoints": "models",
        "unet": "models",
        "diffusion_models": "models",
        "clip": "clips",
        "text_encoders": "clips",
        "vae": "vaes",
        "loras": "loras",
        "upscale_models": "upscalers",
        "controlnet": "controlnets",
    }
    seen = {k: set() for k in buckets}
    for idx, root in enumerate(MODEL_ROOTS):
        for sub, bucket in category_map.items():
            folder = root / sub
            for rel in _walk_model_folder(folder):
                key = (sub.casefold(), rel.casefold(), idx)
                if key in seen[bucket]:
                    continue
                seen[bucket].add(key)
                label = Path(rel).name
                buckets[bucket].append((label, _encode_choice(sub, rel, idx)))
    # Also scan loose LoRA folders that are not inside a standard ComfyUI model root.
    for extra_idx, folder in enumerate(EXTRA_LORA_DIRS, start=len(MODEL_ROOTS)):
        for rel in _walk_model_folder(folder):
            label = Path(rel).name
            value = _encode_choice("loras", rel, extra_idx)
            if not any(v == value for _, v in buckets["loras"]):
                buckets["loras"].append((label, value))

    for key in buckets:
        # Preserve configured root priority: local C: ComfyUI roots first, then D: roots.
        buckets[key].sort(key=lambda x: (_decode_choice(x[1])[2], x[0].casefold()))
    return buckets


def _remote_dropdown_values(node_name: str, input_name: str) -> List[str]:
    """Return a ComfyUI node dropdown's values without needing shell access to the Pod."""
    info = get_object_info()
    try:
        raw = info[node_name]["input"]["required"][input_name][0]
        return [str(x) for x in raw] if isinstance(raw, list) else []
    except (KeyError, IndexError, TypeError):
        return []


def scan_remote_models() -> Dict[str, List[Tuple[str, str]]]:
    """Scan models exposed by the connected remote ComfyUI API.

    This uses ComfyUI's /object_info dropdown lists, so it works through a
    RunPod proxy without SSH or filesystem access.
    """
    buckets: Dict[str, List[Tuple[str, str]]] = {
        "models": [], "clips": [], "vaes": [], "loras": [], "upscalers": [], "controlnets": []
    }
    seen = {key: set() for key in buckets}

    def add(bucket: str, category: str, rel: str) -> None:
        key = (category, rel.casefold())
        if not rel or key in seen[bucket]:
            return
        seen[bucket].add(key)
        buckets[bucket].append((Path(rel).name, _encode_choice(category, rel, 0)))

    for rel in _remote_dropdown_values("CheckpointLoaderSimple", "ckpt_name"):
        add("models", "checkpoints", rel)
    for node in ("UNETLoader", "UnetLoaderGGUF"):
        for rel in _remote_dropdown_values(node, "unet_name"):
            low = rel.casefold()
            category = "unet" if low.endswith(".gguf") or "qwen" in low else "diffusion_models"
            add("models", category, rel)
    for node in ("CLIPLoader", "CLIPLoaderGGUF"):
        for rel in _remote_dropdown_values(node, "clip_name"):
            add("clips", "text_encoders", rel)
    for rel in _remote_dropdown_values("VAELoader", "vae_name"):
        add("vaes", "vae", rel)
    for rel in _remote_dropdown_values("LoraLoader", "lora_name"):
        add("loras", "loras", rel)
    for rel in _remote_dropdown_values("UpscaleModelLoader", "model_name"):
        add("upscalers", "upscale_models", rel)
    for node in ("ControlNetLoader", "ControlNetLoaderAdvanced"):
        for rel in _remote_dropdown_values(node, "control_net_name"):
            add("controlnets", "controlnet", rel)
    for bucket in buckets.values():
        bucket.sort(key=lambda pair: pair[0].casefold())
    return buckets


def current_scans() -> Dict[str, List[Tuple[str, str]]]:
    # Only offer models the active ComfyUI backend can actually load.
    return scan_remote_models()


def choice_rel(value: Optional[str]) -> str:
    return _decode_choice(value)[1]


def choice_category(value: Optional[str]) -> str:
    return _decode_choice(value)[0]


def choose_choice(choices: List[Tuple[str, str]], needles: List[str]) -> Optional[str]:
    for needle in needles:
        for label, value in choices:
            if needle.casefold() in label.casefold():
                return value
    return choices[0][1] if choices else None


# ============================================================================
# FAMILY / RECOMMENDATIONS / LORA FILTERING
# ============================================================================

def detect_family(model_value: Optional[str], override: str = "Auto") -> str:
    if not model_value:
        return override if override and override != "Auto" else "Checkpoint / Unknown"
    cat, rel, _ = _decode_choice(model_value)
    s = rel.casefold().replace("\\", "/")
    # These two known model families must win over a stale saved family
    # dropdown.  Otherwise a Qwen GGUF can accidentally be sent through the
    # checkpoint-only path after an older GUI session.
    if "qwen" in s and ("rapid" in s or "phroot" in s or "phr00t" in s):
        return "Qwen Rapid"
    if "aisha" in s:
        return "FLUX.2 Klein"
    if override and override != "Auto":
        return override
    if "klein" in s or "flux-2" in s or "flux2" in s:
        return "FLUX.2 Klein"
    if cat == "checkpoints":
        if any(x in s for x in ("pony", "sdxl", "juggernaut-xl", "juggernaut_xl", "xl_v", "xl-v")):
            return "SDXL / Pony"
        if any(x in s for x in ("realistic_vision", "dreamshaper", "sd15", "sd1.5", "1-5")):
            return "SD1.5"
        return "Checkpoint / Unknown"
    return "Checkpoint / Unknown"


def is_klein_9b(model_value: Optional[str]) -> bool:
    name = choice_rel(model_value).casefold()
    return "9b" in name or "9-b" in name or "aisha" in name


def is_model_only_flux_file(model_value: Optional[str]) -> bool:
    """True for FLUX/Klein weights stored under checkpoints without CLIP/VAE.

    ComfyUI accepts these through CheckpointLoaderSimple, then falls back to a
    diffusion-model-only load.  Its CLIP and VAE outputs are None, so the
    caller must add separate loaders for those components.
    """
    _cat, rel, _ = _decode_choice(model_value) if model_value else ("", "", 0)
    low = rel.casefold()
    return "aisha" in low or "flux2klein" in low or "flux-2-klein" in low


def effective_mode(mode: str, family: str, has_main: bool) -> str:
    # A Qwen Rapid GGUF is a separate UNET pipeline, never a checkpoint.
    # Keep a stale/manual checkpoint selection from routing it into the wrong loader.
    if family == "Qwen Rapid":
        return "Qwen Rapid - Image Edit"
    # Aisha is a Flux.2 Klein 9B diffusion model and needs the separate
    # Flux text-encoder + VAE workflow, even when the mode dropdown was left
    # on an earlier checkpoint setting.
    if family == "FLUX.2 Klein" and mode in ("Checkpoint - Generate", "Checkpoint - Img2Img"):
        return "FLUX.2 Klein - Image Edit" if has_main else "FLUX.2 Klein - Image Generate"
    if mode != "Auto":
        return mode
    if family == "FLUX.2 Klein":
        return "FLUX.2 Klein - Image Edit" if has_main else "FLUX.2 Klein - Image Generate"
    return "Checkpoint - Generate"


def recommendations(model_value: Optional[str], family: str, mode: str) -> Dict[str, Any]:
    name = choice_rel(model_value)
    low = name.casefold()
    if family == "FLUX.2 Klein":
        is_9b = is_klein_9b(model_value)
        is_aisha = "aisha" in low
        steps = 5 if is_9b or is_aisha else (6 if "base" not in low else 12)
        cfg = 1.0 if is_9b or is_aisha else 1.1
        return {
            "sampler": "euler",
            "scheduler": "normal",
            "steps": steps,
            "cfg": cfg,
            "denoise": 0.75 if "Edit" in mode else 1.0,
            "text": (
                f"Model: {name or '(not selected)'}\n"
                f"Family: FLUX.2 Klein{' · 9B' if is_9b else ''}{' · Aisha' if is_aisha else ''}\n"
                f"Starting point: Euler • CFG {cfg} • {steps} steps.\n"
                "Edit denoise: try 0.65–0.85; Generate denoise: 1.0.\n"
                "Auto-selects flux2-vae + matching Qwen text encoder.\n"
                "9B LoRAs only on 9B models; 4B LoRAs only on 4B (stack validated before queue)."
            )
        }
    if family == "Qwen Rapid":
        return {
            "sampler": "euler_ancestral", "scheduler": "beta", "steps": 4, "cfg": 1.2, "denoise": 0.75,
            "text": (
                f"Model: {name or '(not selected)'}\nFamily: Qwen Rapid / Phr00t\n"
                "Starting point: Euler Ancestral • Beta • 4 steps • CFG 1.2.\n"
                "Use a reference image for edit mode. Auto-picks Qwen VL encoder when present."
            )
        }
    if family == "SDXL / Pony":
        return {
            "sampler": "dpmpp_sde", "scheduler": "karras", "steps": 30, "cfg": 8.3, "denoise": 1.0,
            "text": (
                f"Model: {name or '(not selected)'}\nFamily: SDXL / Pony\n"
                "Your supplied Pony workflow uses DPM++ SDE • Karras • 30 steps • CFG 8.3.\n"
                "Treat that as a starting profile; individual Pony/SDXL checkpoints may prefer different CFG."
            )
        }
    if family == "SD1.5":
        return {
            "sampler": "dpmpp_2m", "scheduler": "karras", "steps": 25, "cfg": 7.0, "denoise": 1.0,
            "text": (
                f"Model: {name or '(not selected)'}\nFamily: SD1.5\n"
                "General starting profile: DPM++ 2M • Karras • 25 steps • CFG 7.\n"
                "For img2img, lower denoise preserves more of the source."
            )
        }
    return {
        "sampler": "euler", "scheduler": "normal", "steps": 25, "cfg": 7.0, "denoise": 1.0,
        "text": f"Model: {name or '(not selected)'}\nFamily: {family}\nUse the family override if auto-detection is wrong."
    }


def compatible_lora_choices(all_loras: List[Tuple[str, str]], family: str, show_all: bool) -> List[Tuple[str, str]]:
    none = [("None", "")]
    if show_all or not all_loras:
        return none + all_loras
    needles: Tuple[str, ...]
    if family == "FLUX.2 Klein":
        needles = ("f2k", "klein", "flux2klein", "flux-2-klein")
    elif family == "Qwen Rapid":
        needles = ("qwen",)
    elif family == "SDXL / Pony":
        needles = ("pony", "sdxl", "xl", "lcm")
    elif family == "SD1.5":
        needles = ("sd15", "sd1.5", "1.5", "dream", "realistic")
    else:
        return none + all_loras
    filtered = [(lab, val) for lab, val in all_loras if any(n in lab.casefold() for n in needles)]
    # If name-based filtering finds nothing, don't hide everything from the user.
    return none + (filtered if filtered else all_loras)


def choose_text_encoder(
    clips: List[Tuple[str, str]],
    preset: str,
    current: Optional[str],
    model_value: Optional[str] = None,
) -> Optional[str]:
    """Pick the best text encoder for the selected model.

    Priority for Klein:
      - 9B model → prefer qwen_3_8b / 8b flux2 encoders when present
      - 4B model → prefer qwen_3_4b / 4b encoders
      - Uncensored preset → abl/uncensored GGUF variants
    """
    if preset == "Custom":
        return current
    if preset == "Uncensored":
        return choose_choice(clips, [
            "qwen3-4b-abl", "abl", "uncensored",
            "flux2-klein-4b-uncensored", "flux2-klein-9b-uncensored",
        ])
    if model_value and detect_family(model_value, "Auto") == "Qwen Rapid":
        picked = choose_choice(clips, ["Qwen2.5-VL-7B-Instruct-Q8_0.gguf", "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "qwen2.5-vl"])
        if not picked or "qwen2.5-vl" not in choice_rel(picked).casefold() or "mmproj" in choice_rel(picked).casefold():
            raise ValueError("Qwen Rapid requires a Qwen2.5-VL text encoder; none found")
        return picked
    # Model-aware Official / Auto selection
    if model_value and is_klein_9b(model_value):
        picked = choose_choice(clips, [
            "qwen_3_8b_fp8mixed", "qwen_3_8b", "qwen3-8b", "8b_fp8", "8b",
            "qwen_3_4b_fp4_flux2", "qwen_3_4b", "flux2",
        ])
        return picked
    # 4B Klein / default
    return choose_choice(clips, [
        "qwen_3_4b_fp4_flux2", "qwen_3_4b", "flux-2-klein-4b", "flux2",
        "qwen3-4b", "4b",
    ])


def choose_vae_for_model(
    vaes: List[Tuple[str, str]],
    model_value: Optional[str],
    family: str,
) -> Optional[str]:
    """Auto-pick VAE to match the selected model family."""
    if not vaes:
        return None
    if family in ("FLUX.2 Klein",) or (model_value and "aisha" in choice_rel(model_value).casefold()):
        return choose_choice(vaes, ["flux2-vae", "flux2", "ae.safetensors"])
    if family == "Qwen Rapid":
        return choose_choice(vaes, ["qwen_image_vae", "qwen", "flux2-vae", "ae"])
    if family == "SDXL / Pony":
        return choose_choice(vaes, ["sdxl_vae", "sdxl", "ae"])
    return choose_choice(vaes, ["vae", "ae"])


def validate_lora_stack(model_value: str, family: str, slots: List[Tuple[bool, str]]) -> None:
    """Block known cross-family and Klein 4B/9B mistakes before ComfyUI loads them."""
    model_name = choice_rel(model_value).casefold()
    for enabled, value in slots:
        if not enabled or not value:
            continue
        name = choice_rel(value).casefold()
        if family == "FLUX.2 Klein":
            if "krea" in name or "qwen" in name or "sdxl" in name or "pony" in name:
                raise gr.Error(f"Incompatible LoRA for FLUX.2 Klein: {choice_rel(value)}")
            if "4b" in model_name and "9b" in name:
                raise gr.Error(f"A Klein 9B LoRA cannot be loaded on a Klein 4B model: {choice_rel(value)}")
            if "9b" in model_name and "4b" in name:
                raise gr.Error(f"A Klein 4B LoRA cannot be loaded on a Klein 9B model: {choice_rel(value)}")
        elif family == "Qwen Rapid" and any(x in name for x in ("klein", "f2k", "sdxl", "pony", "krea")):
            raise gr.Error(f"Incompatible Qwen LoRA/adapter: {choice_rel(value)}")


def parse_lora_manager_rows(table: Any) -> List[Tuple[str, float]]:
    """Accept Gradio Dataframe output as pandas, list-of-lists, or list-of-dicts."""
    if table is None:
        return []
    if hasattr(table, "values") and hasattr(table.values, "tolist"):
        table = table.values.tolist()
    rows: List[Tuple[str, float]] = []
    for row in table or []:
        if isinstance(row, dict):
            enabled, name, strength = row.get("Enabled"), row.get("LoRA"), row.get("Strength", 1.0)
        elif isinstance(row, (list, tuple)) and len(row) >= 3:
            enabled, name, strength = row[0], row[1], row[2]
        else:
            continue
        enabled = enabled is True or str(enabled).strip().casefold() in ("true", "1", "yes", "on")
        name = str(name or "").strip()
        if enabled and name:
            rows.append((name, float(strength)))
    return rows


def inject_lora_manager(prompt: Dict[str, Any], table: Any, family: str) -> List[Tuple[str, float]]:
    """Insert ComfyUI-Lora-Manager and rewire MODEL/CLIP consumers to its outputs."""
    rows = parse_lora_manager_rows(table)
    if not rows:
        raise gr.Error("LoraManager is ON, but no enabled LoRA rows were supplied.")
    class_type = "Lora Loader (LoraManager)"
    if not node_available(class_type):
        raise gr.Error("Lora Loader (LoraManager) is not exposed by ComfyUI. Update/enable ComfyUI-Lora-Manager or use the standard 3-slot stack.")
    if "1" not in prompt:
        raise gr.Error("LoraManager cannot be used in an upscale-only workflow without a diffusion model.")
    checkpoint_loader = prompt["1"].get("class_type") == "CheckpointLoaderSimple"
    model_source: List[Any] = ["1", 0]
    clip_source: List[Any] = ["1", 1] if checkpoint_loader else ["2", 0]
    lora_text = " ".join(
        f"<lora:{Path(name.replace(chr(92), '/')).with_suffix('').as_posix()}:{strength:.2f}>"
        for name, strength in rows
    )
    manager_id = "93"
    prompt[manager_id] = {
        "class_type": class_type,
        "inputs": filtered_inputs(class_type, {
            "model": model_source, "clip": clip_source, "text": lora_text,
        }),
    }

    def replace_refs(value: Any) -> Any:
        if value == model_source:
            return [manager_id, 0]
        if value == clip_source:
            return [manager_id, 1]
        if isinstance(value, dict):
            return {k: replace_refs(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace_refs(v) for v in value]
        return value

    for node_id in list(prompt):
        if node_id != manager_id:
            prompt[node_id]["inputs"] = replace_refs(prompt[node_id].get("inputs", {}))
    return rows


# ============================================================================
# COMFYUI API HELPERS
# ============================================================================

def comfy_alive(timeout: float = 2.0) -> bool:
    if not COMFY_URL:
        return False
    try:
        r = requests.get(f"{COMFY_URL}/system_stats", timeout=timeout)
        return r.ok
    except Exception:
        return False


def get_object_info(force: bool = False) -> Dict[str, Any]:
    global _object_info_cache
    if not COMFY_URL:
        return {}
    if _object_info_cache is not None and not force:
        return _object_info_cache
    try:
        r = requests.get(f"{COMFY_URL}/object_info", timeout=10)
        r.raise_for_status()
        _object_info_cache = r.json()
    except Exception:
        _object_info_cache = {}
    return _object_info_cache


def node_available(class_type: str) -> bool:
    info = get_object_info()
    return class_type in info if info else True  # allow standard nodes if object_info unavailable


def node_input_names(class_type: str) -> set[str]:
    info = get_object_info()
    node = info.get(class_type, {}) if info else {}
    inputs = node.get("input", {}) if isinstance(node, dict) else {}
    names: set[str] = set()
    for section in ("required", "optional"):
        part = inputs.get(section, {})
        if isinstance(part, dict):
            names.update(part.keys())
    return names


def filtered_inputs(class_type: str, values: Dict[str, Any]) -> Dict[str, Any]:
    names = node_input_names(class_type)
    if not names:
        return values
    return {k: v for k, v in values.items() if k in names}


def snap16(n: float) -> int:
    n = int(round(float(n)))
    return max(64, int(round(n / 16.0)) * 16)


def pilify(image: Any) -> Optional[Image.Image]:
    if image is None:
        return None
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    return Image.fromarray(image).convert("RGB")


def upload_image(image: Image.Image, filename: str) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    r = requests.post(
        f"{COMFY_URL}/upload/image",
        files={"image": (filename, buf, "image/png")},
        data={"overwrite": "true"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["name"]


def resolve_size(main: Optional[Image.Image], use_source: bool, preserve_aspect: bool, width: int, height: int) -> Tuple[int, int, str]:
    if use_source:
        if main is None:
            raise gr.Error("Use source resolution is ON, but no main image is loaded.")
        return snap16(main.width), snap16(main.height), "source"
    w = snap16(width)
    h = snap16(height)
    if preserve_aspect and main is not None:
        ratio = main.height / max(1, main.width)
        h = snap16(w * ratio)
        return w, h, "manual + source aspect"
    return w, h, "manual"


def load_diffusion_model(model_value: str) -> Tuple[Dict[str, Any], List[Any], str]:
    """Return node, model reference, and human loader description.

    - GGUF → UnetLoaderGGUF
    - Checkpoint (incl. big Aisha) → CheckpointLoaderSimple (MODEL+CLIP+VAE)
    - Otherwise → UNETLoader
    """
    cat, rel, _ = _decode_choice(model_value)
    low = rel.casefold()
    if low.endswith(".gguf"):
        if not node_available("UnetLoaderGGUF"):
            raise gr.Error("GGUF model selected but UnetLoaderGGUF is not installed (ComfyUI-GGUF required).")
        node = {"class_type": "UnetLoaderGGUF", "inputs": filtered_inputs("UnetLoaderGGUF", {"unet_name": rel})}
        return node, ["1", 0], "UnetLoaderGGUF"
    # Full checkpoints (Aisha betaV87, Pony, etc.)
    if cat == "checkpoints" or low.endswith((".ckpt",)):
        node = {
            "class_type": "CheckpointLoaderSimple",
            "inputs": filtered_inputs("CheckpointLoaderSimple", {"ckpt_name": rel}),
        }
        return node, ["1", 0], "CheckpointLoaderSimple"
    dtype = "fp8_e4m3fn" if "fp8" in low else "default"
    node = {
        "class_type": "UNETLoader",
        "inputs": filtered_inputs("UNETLoader", {"unet_name": rel, "weight_dtype": dtype}),
    }
    return node, ["1", 0], f"UNETLoader ({dtype})"


def load_text_encoder(clip_value: str, family: str) -> Tuple[Dict[str, Any], List[Any], str]:
    rel = choice_rel(clip_value)
    low = rel.casefold()
    clip_type = "flux2" if family == "FLUX.2 Klein" else "qwen_image"
    if low.endswith(".gguf"):
        if not node_available("CLIPLoaderGGUF"):
            raise gr.Error("GGUF text encoder selected but CLIPLoaderGGUF is not installed (ComfyUI-GGUF required).")
        vals = {"clip_name": rel, "type": clip_type, "device": "default"}
        return {"class_type": "CLIPLoaderGGUF", "inputs": filtered_inputs("CLIPLoaderGGUF", vals)}, ["2", 0], "CLIPLoaderGGUF"
    vals = {"clip_name": rel, "type": clip_type, "device": "default"}
    return {"class_type": "CLIPLoader", "inputs": filtered_inputs("CLIPLoader", vals)}, ["2", 0], "CLIPLoader"


def maybe_model_only_lora(prompt: Dict[str, Any], model_ref: List[Any], use_lora: bool, lora_value: str, strength: float, node_id: str = "90") -> List[Any]:
    if not use_lora or not lora_value:
        return model_ref
    rel = choice_rel(lora_value)
    if not node_available("LoraLoaderModelOnly"):
        raise gr.Error("LoraLoaderModelOnly is not available in this ComfyUI installation.")
    prompt[node_id] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": filtered_inputs("LoraLoaderModelOnly", {
            "model": model_ref, "lora_name": rel, "strength_model": float(strength)
        })
    }
    return [node_id, 0]


def maybe_checkpoint_lora(prompt: Dict[str, Any], model_ref: List[Any], clip_ref: List[Any], use_lora: bool, lora_value: str, strength: float, node_id: str = "90") -> Tuple[List[Any], List[Any]]:
    if not use_lora or not lora_value:
        return model_ref, clip_ref
    rel = choice_rel(lora_value)
    if node_available("LoraLoader"):
        prompt[node_id] = {
            "class_type": "LoraLoader",
            "inputs": filtered_inputs("LoraLoader", {
                "model": model_ref, "clip": clip_ref, "lora_name": rel,
                "strength_model": float(strength), "strength_clip": float(strength),
            })
        }
        return [node_id, 0], [node_id, 1]
    # Fallback to model-only if normal loader is missing.
    model_ref = maybe_model_only_lora(prompt, model_ref, True, lora_value, strength, node_id)
    return model_ref, clip_ref


def add_save(prompt: Dict[str, Any], image_ref: List[Any], node_id: str = "99", prefix: str = "UniversalGUI") -> None:
    prompt[node_id] = {"class_type": "SaveImage", "inputs": {"images": image_ref, "filename_prefix": prefix}}


def apply_optional_controlnet(
    prompt: Dict[str, Any], positive: List[Any], negative: List[Any],
    pose_name: Optional[str], use_controlnet: bool, controlnet_value: Optional[str],
    strength: float, start_percent: float, end_percent: float,
    loader_id: str = "70", image_id: str = "71", apply_id: str = "72",
) -> Tuple[List[Any], List[Any]]:
    """Apply a user-selected pose ControlNet to conditioning using standard ComfyUI nodes."""
    if not use_controlnet:
        return positive, negative
    if not pose_name:
        raise gr.Error("OpenPose is ON, but no Pose/Skeleton Image is loaded.")
    if not controlnet_value:
        raise gr.Error("OpenPose is ON, but no ControlNet model is selected.")
    if not node_available("ControlNetLoader") or not node_available("ControlNetApplyAdvanced"):
        raise gr.Error("ControlNetLoader and ControlNetApplyAdvanced are required by this ComfyUI installation.")
    if float(start_percent) >= float(end_percent):
        raise gr.Error("ControlNet Start must be lower than ControlNet End.")
    prompt[loader_id] = {
        "class_type": "ControlNetLoader",
        "inputs": {"control_net_name": choice_rel(controlnet_value)},
    }
    prompt[image_id] = {"class_type": "LoadImage", "inputs": {"image": pose_name}}
    values = {
        "positive": positive, "negative": negative,
        "control_net": [loader_id, 0], "image": [image_id, 0],
        "strength": float(strength), "start_percent": float(start_percent),
        "end_percent": float(end_percent),
    }
    prompt[apply_id] = {
        "class_type": "ControlNetApplyAdvanced",
        "inputs": filtered_inputs("ControlNetApplyAdvanced", values),
    }
    return [apply_id, 0], [apply_id, 1]


# ============================================================================
# PIPELINE BUILDERS
# ============================================================================

def build_flux2_prompt(
    model_value: str, clip_value: str, vae_value: str,
    prompt_text: str, negative_text: str,
    main_name: Optional[str], ref_name: Optional[str], use_reference: bool,
    steps: int, cfg: float, seed: int, denoise: float,
    width: int, height: int, sampler: str,
    use_lora: bool, lora_value: str, lora_strength: float,
    use_lora2: bool, lora2_value: str, lora2_strength: float,
    use_lora3: bool, lora3_value: str, lora3_strength: float,
    pose_name: Optional[str], use_controlnet: bool, controlnet_value: Optional[str],
    controlnet_strength: float, controlnet_start: float, controlnet_end: float,
    scale_method: str, scale_megapixels: float, resolution_steps: int,
    flux_zero_negative: bool, generate_mode: bool,
) -> Tuple[Dict[str, Any], str]:
    p: Dict[str, Any] = {}
    model_node, model_ref, model_loader = load_diffusion_model(model_value)
    p["1"] = model_node

    # Aisha/FLUX weights in the checkpoints folder load through
    # CheckpointLoaderSimple, but ComfyUI reports them as diffusion-model-only:
    # output 0 is valid while outputs 1/2 (CLIP/VAE) are None.  Give these files
    # the same explicit text-encoder + FLUX.2 VAE path as separated UNET models.
    using_checkpoint = (
        model_node.get("class_type") == "CheckpointLoaderSimple"
        and not is_model_only_flux_file(model_value)
    )
    if using_checkpoint:
        clip_ref: List[Any] = ["1", 1]
        vae_ref: List[Any] = ["1", 2]
        clip_loader = "embedded CLIP (checkpoint)"
        # LoRAs on checkpoints need model+clip path
        model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora, lora_value, lora_strength, "90")
        model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora2, lora2_value, lora2_strength, "91")
        model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora3, lora3_value, lora3_strength, "92")
    else:
        clip_node, clip_ref, clip_loader = load_text_encoder(clip_value, "FLUX.2 Klein")
        p["2"] = clip_node
        # FLUX.2 Klein requires the FLUX.2 VAE latent format.
        vae_rel = choice_rel(vae_value)
        if "flux2-vae" not in vae_rel.casefold():
            flux2_vae_choice = choose_choice(SCANS["vaes"], ["flux2-vae"])
            if not flux2_vae_choice or "flux2-vae" not in choice_rel(flux2_vae_choice).casefold():
                raise gr.Error(
                    "FLUX.2 Klein requires flux2-vae.safetensors, but no FLUX.2 VAE was found. "
                    "Put flux2-vae.safetensors in a scanned ComfyUI VAE folder and Refresh Models."
                )
            vae_rel = choice_rel(flux2_vae_choice)
        p["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae_rel}}
        vae_ref = ["3", 0]
        model_ref = maybe_model_only_lora(p, model_ref, use_lora, lora_value, lora_strength, "90")
        model_ref = maybe_model_only_lora(p, model_ref, use_lora2, lora2_value, lora2_strength, "91")
        model_ref = maybe_model_only_lora(p, model_ref, use_lora3, lora3_value, lora3_strength, "92")

    p["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": clip_ref}}
    pos_ref: List[Any] = ["4", 0]
    if flux_zero_negative:
        # FLUX zero-negative mode: mirror the supplied Klein workflow's
        # ConditioningZeroOut fallback. This deliberately ignores negative_text
        # and creates a zeroed conditioning tensor from the positive branch.
        p["5"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": pos_ref}}
        neg_ref: List[Any] = ["5", 0]
    else:
        # Real text negative mode.
        p["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative_text or "", "clip": clip_ref}}
        neg_ref: List[Any] = ["5", 0]

    if not generate_mode:
        if not main_name:
            raise gr.Error("FLUX.2 Klein edit mode requires a Main Image.")
        p["10"] = {"class_type": "LoadImage", "inputs": {"image": main_name}}
        p["11"] = {
            "class_type": "ImageScaleToTotalPixels",
            "inputs": filtered_inputs("ImageScaleToTotalPixels", {
                "image": ["10", 0], "upscale_method": scale_method,
                "megapixels": float(scale_megapixels), "resolution_steps": int(resolution_steps)
            })
        }
        p["12"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": vae_ref}}
        p["13"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos_ref, "latent": ["12", 0]}}
        p["14"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg_ref, "latent": ["12", 0]}}
        pos_ref, neg_ref = ["13", 0], ["14", 0]

        if use_reference:
            if not ref_name:
                raise gr.Error("Use Reference Image is ON, but no Reference Image is loaded.")
            p["15"] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
            p["16"] = {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": filtered_inputs("ImageScaleToTotalPixels", {
                    "image": ["15", 0], "upscale_method": scale_method,
                    "megapixels": float(scale_megapixels), "resolution_steps": int(resolution_steps)
                })
            }
            p["17"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["16", 0], "vae": vae_ref}}
            p["18"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos_ref, "latent": ["17", 0]}}
            p["19"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg_ref, "latent": ["17", 0]}}
            pos_ref, neg_ref = ["18", 0], ["19", 0]

    pos_ref, neg_ref = apply_optional_controlnet(
        p, pos_ref, neg_ref, pose_name, use_controlnet, controlnet_value,
        controlnet_strength, controlnet_start, controlnet_end,
    )

    p["20"] = {"class_type": "CFGGuider", "inputs": {"model": model_ref, "positive": pos_ref, "negative": neg_ref, "cfg": float(cfg)}}
    p["21"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}}
    p["22"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler}}
    p["23"] = {"class_type": "Flux2Scheduler", "inputs": {"steps": int(steps), "width": int(width), "height": int(height)}}
    sigmas_ref: List[Any] = ["23", 0]
    if float(denoise) < 0.999 and node_available("SplitSigmasDenoise"):
        p["24"] = {"class_type": "SplitSigmasDenoise", "inputs": {"sigmas": sigmas_ref, "denoise": float(denoise)}}
        sigmas_ref = ["24", 1]
    p["25"] = {"class_type": "EmptyLatentImage", "inputs": {"width": int(width), "height": int(height), "batch_size": 1}}
    p["26"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {"noise": ["21", 0], "guider": ["20", 0], "sampler": ["22", 0], "sigmas": sigmas_ref, "latent_image": ["25", 0]}
    }
    p["27"] = {"class_type": "VAEDecode", "inputs": {"samples": ["26", 0], "vae": vae_ref}}
    add_save(p, ["27", 0], "99", "Flux2Universal")
    vae_label = "embedded" if using_checkpoint else choice_rel(vae_value)
    return p, f"{model_loader} + {clip_loader} + VAE:{vae_label}"


def build_qwen_prompt(
    model_value: str, clip_value: str, vae_value: str,
    prompt_text: str, negative_text: str, main_name: str, ref_name: Optional[str], use_reference: bool,
    steps: int, cfg: float, seed: int, denoise: float, width: int, height: int,
    sampler: str, scheduler: str,
    use_lora: bool, lora_value: str, lora_strength: float,
    use_lora2: bool, lora2_value: str, lora2_strength: float,
    use_lora3: bool, lora3_value: str, lora3_strength: float,
) -> Tuple[Dict[str, Any], str]:
    p: Dict[str, Any] = {}
    if choice_category(model_value) == "checkpoints":
        p["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": choice_rel(model_value)}}
        model_ref, clip_ref, vae_ref = ["1", 0], ["1", 1], ["1", 2]
        model_loader, clip_loader = "CheckpointLoaderSimple (Qwen AIO)", "embedded CLIP"
    else:
        model_node, model_ref, model_loader = load_diffusion_model(model_value)
        p["1"] = model_node
        clip_node, clip_ref, clip_loader = load_text_encoder(clip_value, "Qwen Rapid")
        p["2"] = clip_node
        vae_rel = choice_rel(vae_value)
        p["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae_rel}}
        vae_ref = ["3", 0]
    model_ref = maybe_model_only_lora(p, model_ref, use_lora, lora_value, lora_strength, "90")
    model_ref = maybe_model_only_lora(p, model_ref, use_lora2, lora2_value, lora2_strength, "91")
    model_ref = maybe_model_only_lora(p, model_ref, use_lora3, lora3_value, lora3_strength, "92")
    p["4"] = {"class_type": "LoadImage", "inputs": {"image": main_name}}
    if not node_available("TextEncodeQwenImageEditPlus"):
        raise gr.Error("TextEncodeQwenImageEditPlus is not installed in ComfyUI.")
    enc_inputs: Dict[str, Any] = {"clip": clip_ref, "vae": vae_ref, "image1": ["4", 0], "prompt": prompt_text, "text": prompt_text}
    if use_reference:
        if not ref_name:
            raise gr.Error("Use Reference Image is ON, but no Reference Image is loaded.")
        p["11"] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
        names = node_input_names("TextEncodeQwenImageEditPlus")
        if "image2" in names:
            enc_inputs["image2"] = ["11", 0]
        else:
            raise gr.Error("Your installed TextEncodeQwenImageEditPlus node does not expose an image2 input for a second reference.")
    p["5"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": filtered_inputs("TextEncodeQwenImageEditPlus", enc_inputs)}

    # Real negative-prompt conditioning for Qwen Rapid.  Use a second
    # TextEncodeQwenImageEditPlus branch instead of ConditioningZeroOut so
    # the text entered in the GUI is actually supplied to KSampler.
    neg_inputs: Dict[str, Any] = {
        "clip": clip_ref, "vae": vae_ref, "image1": ["4", 0],
        "prompt": negative_text or "", "text": negative_text or ""
    }
    if use_reference and ref_name:
        names = node_input_names("TextEncodeQwenImageEditPlus")
        if "image2" in names:
            neg_inputs["image2"] = ["11", 0]
    p["6"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": filtered_inputs("TextEncodeQwenImageEditPlus", neg_inputs)}

    p["7"] = {"class_type": "EmptyLatentImage", "inputs": {"width": int(width), "height": int(height), "batch_size": 1}}
    p["8"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref, "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
            "seed": int(seed), "steps": int(steps), "cfg": float(cfg), "sampler_name": sampler,
            "scheduler": scheduler, "denoise": float(denoise)
        }
    }
    p["9"] = {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": vae_ref}}
    add_save(p, ["9", 0], "99", "QwenRapidUniversal")
    return p, f"{model_loader} + {clip_loader}"


def build_checkpoint_prompt(
    model_value: str, prompt_text: str, negative_text: str,
    main_name: Optional[str], generate_mode: bool,
    steps: int, cfg: float, seed: int, denoise: float, width: int, height: int,
    sampler: str, scheduler: str,
    use_lora: bool, lora_value: str, lora_strength: float,
    use_lora2: bool, lora2_value: str, lora2_strength: float,
    use_lora3: bool, lora3_value: str, lora3_strength: float,
    pose_name: Optional[str], use_controlnet: bool, controlnet_value: Optional[str],
    controlnet_strength: float, controlnet_start: float, controlnet_end: float,
) -> Tuple[Dict[str, Any], str]:
    rel = choice_rel(model_value)
    if choice_category(model_value) != "checkpoints":
        raise gr.Error("Checkpoint modes require a model from a checkpoints folder.")
    p: Dict[str, Any] = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": rel}}
    }
    model_ref: List[Any] = ["1", 0]
    clip_ref: List[Any] = ["1", 1]
    vae_ref: List[Any] = ["1", 2]
    model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora, lora_value, lora_strength, "90")
    model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora2, lora2_value, lora2_strength, "91")
    model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora3, lora3_value, lora3_strength, "92")
    p["2"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": clip_ref}}
    p["3"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative_text or "", "clip": clip_ref}}
    positive_ref, negative_ref = apply_optional_controlnet(
        p, ["2", 0], ["3", 0], pose_name, use_controlnet, controlnet_value,
        controlnet_strength, controlnet_start, controlnet_end,
    )
    if generate_mode:
        p["4"] = {"class_type": "EmptyLatentImage", "inputs": {"width": int(width), "height": int(height), "batch_size": 1}}
        latent_ref: List[Any] = ["4", 0]
    else:
        if not main_name:
            raise gr.Error("Checkpoint Img2Img requires a Main Image.")
        p["4"] = {"class_type": "LoadImage", "inputs": {"image": main_name}}
        p["5"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["4", 0], "vae": vae_ref}}
        latent_ref = ["5", 0]
    p["6"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref, "positive": positive_ref, "negative": negative_ref, "latent_image": latent_ref,
            "seed": int(seed), "steps": int(steps), "cfg": float(cfg), "sampler_name": sampler,
            "scheduler": scheduler, "denoise": float(denoise)
        }
    }
    p["7"] = {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": vae_ref}}
    add_save(p, ["7", 0], "99", "CheckpointUniversal")
    return p, "CheckpointLoaderSimple"


def build_upscale_prompt(
    model_value: str, clip_value: str, vae_value: Optional[str], upscale_value: str, family: str,
    prompt_text: str, negative_text: str, main_name: str,
    steps: int, cfg: float, seed: int, denoise: float,
    sampler: str, scheduler: str,
    use_lora: bool, lora_value: str, lora_strength: float,
    use_lora2: bool, lora2_value: str, lora2_strength: float,
    use_lora3: bool, lora3_value: str, lora3_strength: float,
    upscale_by: float,
) -> Tuple[Dict[str, Any], str]:
    if not node_available("UltimateSDUpscale"):
        raise gr.Error("UltimateSDUpscale is not installed in this ComfyUI.")
    rel = choice_rel(model_value)
    up_rel = choice_rel(upscale_value)
    p: Dict[str, Any] = {}
    if choice_category(model_value) == "checkpoints":
        p["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": rel}}
        model_ref, clip_ref, vae_ref = ["1", 0], ["1", 1], ["1", 2]
        model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora, lora_value, lora_strength, "90")
        model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora2, lora2_value, lora2_strength, "91")
        model_ref, clip_ref = maybe_checkpoint_lora(p, model_ref, clip_ref, use_lora3, lora3_value, lora3_strength, "92")
        loader_desc = "CheckpointLoaderSimple"
    elif family == "FLUX.2 Klein":
        model_node, model_ref, loader_desc = load_diffusion_model(model_value)
        clip_node, clip_ref, clip_desc = load_text_encoder(clip_value, family)
        p["1"], p["2"] = model_node, clip_node
        flux_vae = choose_choice(SCANS["vaes"], ["flux2-vae"])
        if not flux_vae:
            raise gr.Error("FLUX.2 Ultimate Upscale requires flux2-vae.safetensors.")
        p["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": choice_rel(flux_vae)}}
        vae_ref = ["3", 0]
        model_ref = maybe_model_only_lora(p, model_ref, use_lora, lora_value, lora_strength, "90")
        model_ref = maybe_model_only_lora(p, model_ref, use_lora2, lora2_value, lora2_strength, "91")
        model_ref = maybe_model_only_lora(p, model_ref, use_lora3, lora3_value, lora3_strength, "92")
        loader_desc += f" + {clip_desc} (experimental Ultimate FLUX route)"
    else:
        raise gr.Error("Ultimate upscale supports SDXL/SD1.5 checkpoints or FLUX.2 Klein separated models.")
    p["10"] = {"class_type": "LoadImage", "inputs": {"image": main_name}}
    p["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": clip_ref}}
    p["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative_text or "", "clip": clip_ref}}
    p["6"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": up_rel}}
    vals = {
        "image": ["10", 0], "model": model_ref, "positive": ["4", 0], "negative": ["5", 0],
        "vae": vae_ref, "upscale_model": ["6", 0], "upscale_by": float(upscale_by),
        "seed": int(seed), "steps": int(steps), "cfg": float(cfg), "sampler_name": sampler,
        "scheduler": scheduler, "denoise": float(denoise), "mode_type": "Linear",
        "tile_width": 512, "tile_height": 512, "mask_blur": 8, "tile_padding": 32,
        "seam_fix_mode": "None", "seam_fix_denoise": 1.0, "seam_fix_width": 64,
        "seam_fix_mask_blur": 8, "seam_fix_padding": 16, "force_uniform_tiles": True,
        "tiled_decode": False, "batch_size": 1,
    }
    p["7"] = {"class_type": "UltimateSDUpscale", "inputs": filtered_inputs("UltimateSDUpscale", vals)}
    add_save(p, ["7", 0], "99", "UniversalUpscale")
    return p, loader_desc + " + UltimateSDUpscale"


def build_standard_upscale_prompt(
    upscale_value: str, main_name: str, source_width: int, source_height: int,
    upscale_by: float,
) -> Tuple[Dict[str, Any], str]:
    """Run ESRGAN/UltraSharp then resize its native output to an exact multiplier."""
    up_rel = choice_rel(upscale_value)
    target_w = snap16(float(source_width) * float(upscale_by))
    target_h = snap16(float(source_height) * float(upscale_by))
    p: Dict[str, Any] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": main_name}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": up_rel}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "ImageScale", "inputs": filtered_inputs("ImageScale", {
            "image": ["3", 0], "upscale_method": "lanczos",
            "width": target_w, "height": target_h, "crop": "disabled",
        })},
    }
    add_save(p, ["4", 0], "99", "StandardModelUpscale")
    return p, f"{up_rel} → exact {float(upscale_by):.2f}× ({target_w}×{target_h})"


# ============================================================================
# GENERATION / HISTORY

def wan21_choices(force=False):
    if force:
        get_object_info(force=True)
    models = [v for v in _remote_dropdown_values("UNETLoader", "unet_name")
              if ("wan2.1" in v.lower() or "wan2_1" in v.lower()) and "i2v" in v.lower()]
    loras = [v for v in _remote_dropdown_values("LoraLoaderModelOnly", "lora_name")
             if "wan" in v.lower() and ".genesis-upload-partial" not in v]
    return models, loras


def wan21_refresh():
    models, loras = wan21_choices(True)
    return (gr.update(choices=models, value=models[0] if models else None),
            gr.update(choices=["None"] + loras, value="None"),
            f"WAN 2.1 I2V models: {len(models)} | WAN LoRAs: {len(loras)}")


def wan21_build(model, image_name, prompt, negative, width, height, frames,
                fps, steps, cfg, seed, shift, lora, strength):
    info = get_object_info()
    def require_file(node, field, name):
        choices = info.get(node, {}).get("input", {}).get("required", {}).get(field, [[]])[0]
        if name not in choices:
            raise gr.Error(f"Missing {name}. Check the connected ComfyUI model folder.")
        return name
    model = require_file("UNETLoader", "unet_name", model)
    encoder = require_file("CLIPLoader", "clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors")
    vae = require_file("VAELoader", "vae_name", "wan_2.1_vae.safetensors")
    vision = require_file("CLIPVisionLoader", "clip_name", "clip_vision_h.safetensors")
    for node in ("WanImageToVideo", "CreateVideo", "SaveVideo", "ModelSamplingSD3"):
        if node not in info:
            raise gr.Error(f"Missing ComfyUI node: {node}")
    frames = int(frames)
    if frames < 5 or (frames - 1) % 4:
        raise gr.Error("Frames must be 4n+1: 17, 33, 49, 65, 81, etc.")
    if not 1 <= float(fps) <= 120:
        raise gr.Error("FPS must be between 1 and 120.")
    width, height = snap16(width), snap16(height)
    p = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": model, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": encoder, "type": "wan", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": vision}},
        "6": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["5", 0], "image": ["4", 0], "crop": "center"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        "9": {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["7", 0], "negative": ["8", 0], "vae": ["3", 0],
            "clip_vision_output": ["6", 0], "start_image": ["4", 0],
            "width": width, "height": height, "length": frames, "batch_size": 1}},
        "10": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": float(shift)}},
        "11": {"class_type": "KSampler", "inputs": {
            "model": ["10", 0], "positive": ["9", 0], "negative": ["9", 1],
            "latent_image": ["9", 2], "seed": int(seed), "steps": int(steps),
            "cfg": float(cfg), "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "fps": float(fps)}},
        "14": {"class_type": "SaveVideo", "inputs": {
            "video": ["13", 0], "filename_prefix": "MUNG_WAN21",
            "format": "mp4", "codec": "auto"}},
    }
    if lora and lora != "None":
        require_file("LoraLoaderModelOnly", "lora_name", lora)
        p["15"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["1", 0], "lora_name": lora, "strength_model": float(strength)}}
        p["10"]["inputs"]["model"] = ["15", 0]
    return p, width, height


def wan21_generate(model, image, prompt, negative, width, height, frames,
                   fps, steps, cfg, seed, shift, lora, strength,
                   progress=gr.Progress()):
    global _current_prompt_id, _cancel_requested
    _cancel_requested = False
    if not comfy_alive(5):
        raise gr.Error(f"Cannot reach ComfyUI at {COMFY_URL}")
    get_object_info(force=True)
    picture = pilify(image)
    if picture is None:
        raise gr.Error("Upload a starting image.")
    if not str(prompt).strip():
        raise gr.Error("Enter a motion prompt.")
    real_seed = random.randint(0, 2**63 - 1) if seed is None or int(seed) < 0 else int(seed)
    progress(0.02, desc="Uploading starting image")
    image_name = upload_image(picture, "mung_wan_start.png")
    graph, width, height = wan21_build(model, image_name, prompt, negative,
        width, height, frames, fps, steps, cfg, real_seed, shift, lora, strength)
    response = requests.post(f"{COMFY_URL}/prompt", json={"prompt": graph}, timeout=30)
    if not response.ok:
        raise gr.Error(f"ComfyUI rejected WAN workflow: {response.text}")
    _current_prompt_id = response.json()["prompt_id"]
    began = time.time()
    while time.time() - began < 3600:
        if _cancel_requested:
            raise gr.Error("Video generation interrupted.")
        history_response = requests.get(f"{COMFY_URL}/history/{_current_prompt_id}", timeout=30)
        history_response.raise_for_status()
        history = history_response.json()
        item = history.get(_current_prompt_id)
        if item:
            status = item.get("status", {})
            if status.get("status_str") == "error":
                raise gr.Error(f"WAN failed: {status.get('messages', [])}")
            for output in item.get("outputs", {}).values():
                for key in ("images", "videos", "gifs"):
                    for meta in output.get(key, []) if isinstance(output, dict) else []:
                        filename = meta.get("filename", "")
                        if not filename.lower().endswith((".mp4", ".webm", ".mov")):
                            continue
                        fetched = requests.get(f"{COMFY_URL}/view", params={
                            "filename": filename, "subfolder": meta.get("subfolder", ""),
                            "type": meta.get("type", "output")}, timeout=180)
                        fetched.raise_for_status()
                        folder = APP_DIR / "outputs" / "videos"
                        folder.mkdir(parents=True, exist_ok=True)
                        destination = folder / f"{_current_prompt_id}_{Path(filename).name}"
                        destination.write_bytes(fetched.content)
                        progress(1, desc="Video ready")
                        return str(destination), f"{width} x {height} | {int(frames)} frames | {fps} FPS | Seed {real_seed}"
            if status.get("completed"):
                raise gr.Error("WAN finished but no video file was returned. Inspect the SaveVideo node output.")
        elapsed = int(time.time() - began)
        progress(min(.95, .1 + elapsed / 3600 * .85), desc=f"Generating video: {elapsed}s")
        time.sleep(2)
    raise gr.Error("Timed out waiting for WAN video.")



# ============================================================================

def wait_for_result(prompt_id: str, progress: gr.Progress, timeout_seconds: int = 600) -> Tuple[Image.Image, Dict[str, Any]]:
    global _cancel_requested
    start = time.time()
    while time.time() - start < timeout_seconds:
        if _cancel_requested:
            raise gr.Error("Generation cancelled.")
        time.sleep(1.0)
        try:
            hist = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
        except Exception:
            continue
        if prompt_id in hist:
            item = hist[prompt_id]
            outputs = item.get("outputs", {})
            for _, out in outputs.items():
                images = out.get("images", []) if isinstance(out, dict) else []
                if images:
                    meta = images[0]
                    params = {
                        "filename": meta["filename"], "subfolder": meta.get("subfolder", ""),
                        "type": meta.get("type", "output")
                    }
                    r = requests.get(f"{COMFY_URL}/view", params=params, timeout=60)
                    r.raise_for_status()
                    return Image.open(io.BytesIO(r.content)).copy(), item
        elapsed = int(time.time() - start)
        progress(min(0.95, 0.40 + elapsed / max(1, timeout_seconds) * 0.55), desc=f"Generating… {elapsed}s")
    raise gr.Error("Timed out waiting for ComfyUI.")


def generate(
    mode: str, family_override: str,
    model_value: str, clip_value: str, vae_value: str, upscale_value: str,
    text_encoder_preset: str,
    main_image: Any, reference_image: Any, use_reference: bool,
    pose_image: Any, use_controlnet: bool, controlnet_value: str,
    controlnet_strength: float, controlnet_start: float, controlnet_end: float,
    prompt_text: str, negative_text: str,
    flux_zero_negative: bool,
    use_lora: bool, lora_value: str, lora_strength: float,
    use_lora2: bool, lora2_value: str, lora2_strength: float,
    use_lora3: bool, lora3_value: str, lora3_strength: float,
    use_lora_manager: bool, lora_manager_table: Any,
    steps: int, cfg: float, seed: float, denoise: float, sampler: str, scheduler: str,
    use_source: bool, preserve_aspect: bool, width: int, height: int,
    scale_method: str, scale_megapixels: float, resolution_steps: int,
    upscale_by: float, seed_lock: bool,
    progress=gr.Progress(),
):
    global _current_prompt_id, _cancel_requested
    _cancel_requested = False
    if not comfy_alive(3):
        raise gr.Error(f"Cannot reach ComfyUI at {COMFY_URL}. If using RunPod, reconnect with the current port-8188 proxy URL.")
    get_object_info(force=True)

    if not model_value and mode != "Standard Model Upscale":
        raise gr.Error("Select a model/checkpoint first.")
    if not prompt_text.strip() and mode not in ("Ultimate SD Upscale", "Standard Model Upscale"):
        raise gr.Error("Enter a prompt.")

    main = pilify(main_image)
    ref = pilify(reference_image)
    pose = pilify(pose_image)
    family = detect_family(model_value, family_override)
    eff_mode = effective_mode(mode, family, main is not None)
    validate_lora_stack(model_value, family, [
        (use_lora, lora_value), (use_lora2, lora2_value), (use_lora3, lora3_value)
    ])
    if use_lora_manager and any((use_lora, use_lora2, use_lora3)):
        raise gr.Error("Choose either LoraManager unlimited stack or the standard 3-slot stack, not both.")
    if use_controlnet and eff_mode in ("Qwen Rapid - Image Edit", "Ultimate SD Upscale", "Standard Model Upscale"):
        raise gr.Error(f"OpenPose ControlNet is not connected in {eff_mode}. Turn it off or choose a compatible FLUX/checkpoint mode.")

    # Source resolution is meaningful only for image-driven modes.
    source_capable = eff_mode in ("FLUX.2 Klein - Image Edit", "Qwen Rapid - Image Edit", "Checkpoint - Img2Img")
    out_w, out_h, size_mode = resolve_size(main, bool(use_source and source_capable), preserve_aspect, width, height)

    if seed is None or int(seed) < 0:
        real_seed = random.randint(0, 2**63 - 1)
    else:
        real_seed = int(seed)

    progress(0.05, desc="Uploading images…")
    main_name = upload_image(main, "universal_main.png") if main is not None else None
    ref_name = upload_image(ref, "universal_reference.png") if (use_reference and ref is not None) else None
    pose_name = upload_image(pose, "universal_openpose.png") if (use_controlnet and pose is not None) else None

    # Text encoder preset can override the dropdown for Klein (model-aware 9B vs 4B).
    scans = current_scans()
    actual_clip = clip_value
    if family == "FLUX.2 Klein" and text_encoder_preset != "Custom":
        actual_clip = choose_text_encoder(
            scans["clips"], text_encoder_preset, clip_value, model_value
        ) or clip_value

    progress(0.15, desc=f"Building {eff_mode} pipeline…")
    if eff_mode == "FLUX.2 Klein - Image Edit":
        api_prompt, loader_desc = build_flux2_prompt(
            model_value, actual_clip, vae_value, prompt_text, negative_text,
            main_name, ref_name, use_reference, steps, cfg, real_seed, denoise,
            out_w, out_h, sampler, use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
            pose_name, use_controlnet, controlnet_value, controlnet_strength, controlnet_start, controlnet_end,
            scale_method, scale_megapixels, resolution_steps, flux_zero_negative, False,
        )
    elif eff_mode == "FLUX.2 Klein - Image Generate":
        api_prompt, loader_desc = build_flux2_prompt(
            model_value, actual_clip, vae_value, prompt_text, negative_text,
            None, None, False, steps, cfg, real_seed, 1.0,
            out_w, out_h, sampler, use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
            pose_name, use_controlnet, controlnet_value, controlnet_strength, controlnet_start, controlnet_end,
            scale_method, scale_megapixels, resolution_steps, flux_zero_negative, True,
        )
    elif eff_mode == "Qwen Rapid - Image Edit":
        if not main_name:
            raise gr.Error("Qwen Rapid edit requires a Main Image.")
        api_prompt, loader_desc = build_qwen_prompt(
            model_value, actual_clip, vae_value, prompt_text, negative_text, main_name, ref_name, use_reference,
            steps, cfg, real_seed, denoise, out_w, out_h, sampler, scheduler,
            use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
        )
    elif eff_mode == "Standard Model Upscale":
        if not main_name:
            raise gr.Error("Standard Model Upscale requires a Main Image.")
        if not upscale_value:
            raise gr.Error("Select 4x UltraSharp, ESRGAN, or another upscale model.")
        api_prompt, loader_desc = build_standard_upscale_prompt(
            upscale_value, main_name, main.width, main.height, upscale_by,
        )
    elif eff_mode == "Checkpoint - Img2Img":
        api_prompt, loader_desc = build_checkpoint_prompt(
            model_value, prompt_text, negative_text, main_name, False,
            steps, cfg, real_seed, denoise, out_w, out_h, sampler, scheduler,
            use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
            pose_name, use_controlnet, controlnet_value, controlnet_strength, controlnet_start, controlnet_end,
        )

    manager_rows: List[Tuple[str, float]] = []
    if use_lora_manager:
        if eff_mode == "Standard Model Upscale":
            raise gr.Error("Standard Model Upscale has no diffusion model, so LoRs do not apply.")
        manager_rows = inject_lora_manager(api_prompt, lora_manager_table, family)
    elif eff_mode == "Ultimate SD Upscale":
        if not main_name:
            raise gr.Error("Ultimate SD Upscale requires a Main Image.")
        if not upscale_value:
            raise gr.Error("Select an upscale model.")
        api_prompt, loader_desc = build_upscale_prompt(
            model_value, actual_clip, vae_value, upscale_value, family, prompt_text, negative_text, main_name,
            steps, cfg, real_seed, denoise, sampler, scheduler,
            use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
            upscale_by,
        )
    elif eff_mode == "Checkpoint - Generate":
        api_prompt, loader_desc = build_checkpoint_prompt(
            model_value, prompt_text, negative_text, None, True,
            steps, cfg, real_seed, 1.0, out_w, out_h, sampler, scheduler,
            use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
            pose_name, use_controlnet, controlnet_value, controlnet_strength, controlnet_start, controlnet_end,
        )

    progress(0.30, desc="Queueing…")
    r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": api_prompt}, timeout=30)
    if not r.ok:
        raise gr.Error(f"ComfyUI rejected the workflow:\n{r.text}")
    _current_prompt_id = r.json().get("prompt_id")
    if not _current_prompt_id:
        raise gr.Error("ComfyUI did not return a prompt_id.")

    result, _hist = wait_for_result(_current_prompt_id, progress)
    progress(1.0, desc="Done")

    if prompt_text.strip():
        try:
            _prompt_history.remove(prompt_text.strip())
        except ValueError:
            pass
        _prompt_history.appendleft(prompt_text.strip())
        SETTINGS["prompt_history"] = list(_prompt_history)
        save_settings_dict(SETTINGS)

    info = (
        f"Mode: {eff_mode} | Family: {family} | Seed: {real_seed} | Output: {result.width}×{result.height} "
        f"| Requested: {out_w}×{out_h} ({size_mode}) | Loader: {loader_desc}"
    )
    if use_lora and lora_value:
        info += f" | LoRA: {choice_rel(lora_value)} @ {float(lora_strength):.2f}"
    if use_lora2 and lora2_value:
        info += f" | LoRA 2: {choice_rel(lora2_value)} @ {float(lora2_strength):.2f}"
    if use_lora3 and lora3_value:
        info += f" | LoRA 3: {choice_rel(lora3_value)} @ {float(lora3_strength):.2f}"
    if manager_rows:
        info += " | LoraManager: " + ", ".join(f"{name} @ {strength:.2f}" for name, strength in manager_rows)
    if use_controlnet and controlnet_value:
        info += f" | ControlNet: {choice_rel(controlnet_value)} @ {float(controlnet_strength):.2f}"
    return result, info, gr.update(choices=list(_prompt_history), value=prompt_text.strip() if prompt_text.strip() else None), gr.update(value=real_seed) if seed_lock else gr.update()


def cancel_generation() -> str:
    global _cancel_requested
    _cancel_requested = True
    try:
        r = requests.post(f"{COMFY_URL}/interrupt", timeout=5)
        return "Interrupt sent to ComfyUI." if r.ok else f"Interrupt returned HTTP {r.status_code}."
    except Exception as e:
        return f"Could not interrupt ComfyUI: {e}"


# ============================================================================
# COMFYUI PROCESS CONTROL
# ============================================================================

def _reader_thread(proc: subprocess.Popen) -> None:
    try:
        if proc.stdout is None:
            return
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            _comfy_log.append(line.rstrip())
    except Exception as e:
        _comfy_log.append(f"Log reader stopped: {e}")


def compute_launch_args(
    comfy_python: str, comfy_main: str,
    windows_standalone: bool, preview_none: bool, fast_disk: bool,
    auto_fp8: bool, fp8_unet: bool, fp8_text: bool,
    extra_args: str, model_value: Optional[str], clip_value: Optional[str],
) -> List[str]:
    args = [comfy_python, "-s", comfy_main]
    if windows_standalone:
        args.append("--windows-standalone-build")
    if preview_none:
        args += ["--preview-method", "none"]
    if fast_disk:
        args.append("--fast-disk")
    if auto_fp8:
        # User rule: only apply the FP8 flag when the selected filename itself says FP8.
        if "fp8" in choice_rel(model_value).casefold():
            args.append("--fp8_e4m3fn-unet")
        if "fp8" in choice_rel(clip_value).casefold():
            args.append("--fp8_e4m3fn-text-enc")
    else:
        if fp8_unet:
            args.append("--fp8_e4m3fn-unet")
        if fp8_text:
            args.append("--fp8_e4m3fn-text-enc")
    if extra_args.strip():
        # Basic Windows-friendly split for simple flags. Quoted complex arguments can still be added.
        import shlex
        args += shlex.split(extra_args, posix=False)
    return args


def command_preview(*args) -> str:
    cmd = compute_launch_args(*args)
    return subprocess.list2cmdline(cmd)


def save_startup_settings(
    comfy_python, comfy_main, comfy_output,
    windows_standalone, preview_none, fast_disk, auto_fp8, fp8_unet, fp8_text, extra_args,
) -> str:
    SETTINGS.update({
        "comfy_python": comfy_python, "comfy_main": comfy_main, "comfy_output": comfy_output,
        "windows_standalone": bool(windows_standalone), "preview_none": bool(preview_none),
        "fast_disk": bool(fast_disk), "auto_fp8": bool(auto_fp8),
        "fp8_unet": bool(fp8_unet), "fp8_text": bool(fp8_text), "extra_args": extra_args,
    })
    save_settings_dict(SETTINGS)
    return f"Saved startup settings to {SETTINGS_FILE.name}."


def start_comfy(
    comfy_python: str, comfy_main: str,
    windows_standalone: bool, preview_none: bool, fast_disk: bool,
    auto_fp8: bool, fp8_unet: bool, fp8_text: bool, extra_args: str,
    model_value: Optional[str], clip_value: Optional[str],
) -> str:
    global _owned_comfy_process, _object_info_cache
    if comfy_alive(1):
        return "ComfyUI is already running. This GUI will not start a second instance."
    py = Path(comfy_python)
    main = Path(comfy_main)
    if not py.is_file():
        return f"Python executable not found: {py}"
    if not main.is_file():
        return f"ComfyUI main.py not found: {main}"
    cmd = compute_launch_args(
        comfy_python, comfy_main, windows_standalone, preview_none, fast_disk,
        auto_fp8, fp8_unet, fp8_text, extra_args, model_value, clip_value
    )
    try:
        _comfy_log.clear()
        _comfy_log.append("START: " + subprocess.list2cmdline(cmd))
        _owned_comfy_process = subprocess.Popen(
            cmd,
            cwd=str(main.parent.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=_reader_thread, args=(_owned_comfy_process,), daemon=True).start()
        _object_info_cache = None
        for _ in range(120):
            if comfy_alive(1):
                return f"ComfyUI ready. PID {_owned_comfy_process.pid}."
            if _owned_comfy_process.poll() is not None:
                return "ComfyUI exited during startup. Check the log panel."
            time.sleep(1)
        return "ComfyUI process started but did not become ready within 120 seconds."
    except Exception as e:
        return f"Failed to start ComfyUI: {e}"


def restart_comfy(*args) -> str:
    global _owned_comfy_process, _object_info_cache
    if _owned_comfy_process is None or _owned_comfy_process.poll() is not None:
        if comfy_alive(1):
            return (
                "ComfyUI is running, but it was not started by this GUI. For safety I will not kill an external Python process. "
                "Close that ComfyUI window first, then click Start ComfyUI here."
            )
        return start_comfy(*args)
    try:
        _comfy_log.append("Stopping GUI-owned ComfyUI process…")
        _owned_comfy_process.terminate()
        try:
            _owned_comfy_process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _owned_comfy_process.kill()
            _owned_comfy_process.wait(timeout=5)
        _owned_comfy_process = None
        _object_info_cache = None
        time.sleep(1)
    except Exception as e:
        return f"Could not stop GUI-owned ComfyUI: {e}"
    return start_comfy(*args)


def queue_status_text() -> str:
    if not COMFY_URL:
        return "Paste the current RunPod URL and connect."
    try:
        response = requests.get(f"{COMFY_URL}/queue", timeout=3)
        response.raise_for_status()
        queue = response.json()
        running = len(queue.get("queue_running", []))
        waiting = len(queue.get("queue_pending", []))
        return f"Running: {running}  |  Waiting: {waiting}"
    except Exception:
        return "Queue: unavailable"

def status_text() -> str:
    if not COMFY_URL:
        return "RunPod not connected - paste the current pod URL and click Connect & Scan Pod Models."
    if comfy_alive(1):
        owned = _owned_comfy_process is not None and _owned_comfy_process.poll() is None
        return f"🟢 ComfyUI ONLINE — {COMFY_URL}" + (f" — GUI-owned PID {_owned_comfy_process.pid}" if owned else " — external process")
    return f"🔴 ComfyUI OFFLINE — {COMFY_URL}"


def connect_runpod_and_scan(endpoint: str, family_override: str, model_value: Optional[str], show_all_loras: bool):
    """Switch this GUI to a remote ComfyUI (for example a RunPod proxy) and scan its exposed models."""
    global COMFY_URL, MODEL_SOURCE, _object_info_cache
    endpoint = (endpoint or "").strip().rstrip("/")
    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    if not endpoint:
        raise gr.Error("Enter the RunPod ComfyUI proxy address for port 8188.")
    try:
        test = requests.get(f"{endpoint}/object_info", timeout=15)
        test.raise_for_status()
        payload = test.json()
        if not isinstance(payload, dict) or not payload:
            raise RuntimeError("ComfyUI returned empty object_info")
    except Exception as e:
        raise gr.Error(f"RunPod connection failed: {endpoint} — {e}")
    # Only replace the active connection and remembered URL after validation.
    COMFY_URL = endpoint
    MODEL_SOURCE = "remote"
    _object_info_cache = payload
    SETTINGS["comfy_url"] = COMFY_URL
    SETTINGS["model_source"] = MODEL_SOURCE
    save_settings_dict(SETTINGS)
    updates = refresh_models_ui(family_override, model_value, show_all_loras)
    return (*updates, status_text())


def log_text() -> str:
    return "\n".join(_comfy_log) if _comfy_log else "No GUI-owned ComfyUI log yet."


def open_output_folder(path: str) -> str:
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return f"Opened: {p}"
    except Exception as e:
        return f"Could not open output folder: {e}"


# ============================================================================
# UI HELPERS
# ============================================================================

def refresh_models_ui(family_override: str, model_value: Optional[str], show_all_loras: bool):
    scans = current_scans()
    family = detect_family(model_value, family_override)
    loras = compatible_lora_choices(scans["loras"], family, show_all_loras)
    return (
        gr.update(choices=scans["models"], value=model_value if any(v == model_value for _, v in scans["models"]) else (scans["models"][0][1] if scans["models"] else None)),
        gr.update(choices=scans["clips"]),
        gr.update(choices=scans["vaes"]),
        gr.update(choices=loras, value=""),
        gr.update(choices=loras, value=""),
        gr.update(choices=loras, value=""),
        gr.update(choices=scans["upscalers"]),
        gr.update(choices=scans["controlnets"]),
        f"Scanned — Models: {len(scans['models'])} | Encoders: {len(scans['clips'])} | VAEs: {len(scans['vaes'])} | LoRAs: {len(scans['loras'])} | Upscalers: {len(scans['upscalers'])}",
    )


def on_model_change(model_value, family_override, mode, show_all_loras, text_preset, current_clip):
    """When the user picks a model, auto-fill family, text encoder, VAE, and LoRA lists."""
    scans = current_scans()
    family = detect_family(model_value, family_override)
    eff = effective_mode(mode, family, False)
    rec = recommendations(model_value, family, eff)
    loras = compatible_lora_choices(scans["loras"], family, show_all_loras)

    # Text encoder
    clip = current_clip
    if family == "FLUX.2 Klein":
        clip = choose_text_encoder(scans["clips"], text_preset, current_clip, model_value)
    elif family == "Qwen Rapid":
        clip = choose_choice(scans["clips"], [
            "Qwen2.5-VL-7B-Instruct-Q4_K_M", "Qwen2.5-VL-7B", "qwen2.5-vl",
            "qwen_image", "qwen",
        ])

    # VAE
    vae = choose_vae_for_model(scans["vaes"], model_value, family)

    note = SETTINGS.get("model_notes", {}).get(choice_rel(model_value), "")
    return (
        family,
        rec["text"],
        gr.update(choices=loras, value=""),
        gr.update(choices=loras, value=""),
        gr.update(choices=loras, value=""),
        gr.update(value=clip),
        gr.update(value=vae),
        note,
    )


def apply_recommended(model_value, family_override, mode, main_image):
    family = detect_family(model_value, family_override)
    eff = effective_mode(mode, family, main_image is not None)
    r = recommendations(model_value, family, eff)
    return r["sampler"], r["scheduler"], r["steps"], r["cfg"], r["denoise"]


def save_model_note(model_value: str, note: str) -> str:
    key = choice_rel(model_value)
    if not key:
        return "Select a model first."
    SETTINGS.setdefault("model_notes", {})[key] = note
    save_settings_dict(SETTINGS)
    return f"Saved note for {key}."


def on_lora_toggle(enabled: bool):
    return gr.update(interactive=enabled), gr.update(interactive=enabled)


def on_text_preset(preset: str, current_clip: Optional[str]):
    scans = current_scans()
    chosen = choose_text_encoder(scans["clips"], preset, current_clip)
    return gr.update(value=chosen, interactive=(preset == "Custom"))


def on_mode_change(mode: str):
    is_generate = mode in ("FLUX.2 Klein - Image Generate", "Checkpoint - Generate")
    is_upscale = mode in ("Ultimate SD Upscale", "Standard Model Upscale")
    image_needed = mode in ("FLUX.2 Klein - Image Edit", "Qwen Rapid - Image Edit", "Checkpoint - Img2Img", "Ultimate SD Upscale", "Standard Model Upscale", "Auto")
    reference_supported = mode in ("FLUX.2 Klein - Image Edit", "Qwen Rapid - Image Edit", "Auto")
    negative_supported = True
    return (
        gr.update(visible=image_needed),
        gr.update(visible=reference_supported),
        gr.update(visible=negative_supported),
        gr.update(value=False if is_generate or is_upscale else True, interactive=not is_generate and not is_upscale),
        gr.update(visible=is_upscale),
    )


def on_use_source(use_source: bool, main_image: Any):
    if use_source:
        return gr.update(visible=False), gr.update(), gr.update(), gr.update()
    img = pilify(main_image)
    if img is None:
        return gr.update(visible=True), gr.update(), gr.update(), gr.update()
    return gr.update(visible=True), snap16(img.width), snap16(img.height), "Custom"


def on_width_change(width: int, preserve: bool, main_image: Any):
    img = pilify(main_image)
    if not preserve or img is None:
        return gr.update()
    return snap16(float(width) * img.height / max(1, img.width))


def apply_preset(preset: str):
    size = RES_PRESETS.get(preset)
    if size is None:
        return gr.update(), gr.update()
    return size[0], size[1]


def use_prompt_history(value: Optional[str]):
    return value or ""


# ============================================================================
# INITIAL SCAN / DEFAULTS
# ============================================================================

SCANS = current_scans()
# Prefer 9B Klein → big Aisha → Phr00t/Qwen Rapid → anything Klein → fallback
DEFAULT_MODEL = choose_choice(SCANS["models"], [
    "flux-2-klein-9b-fp8", "flux-2-klein-9b", "klein-9b", "9b-fp8",
    "aishaNSFWFlux2Klein_betaV87", "aishansfwflux2klein", "aisha",
    "Qwen-Rapid-NSFW-v23", "qwen-rapid", "rapid-nsfw",
    "flux-2-klein-4b-fp8", "flux-2-klein-4b", "klein",
    "ponyRealism",
])
DEFAULT_CLIP = choose_text_encoder(SCANS["clips"], "Official", None, DEFAULT_MODEL)
DEFAULT_VAE = choose_vae_for_model(SCANS["vaes"], DEFAULT_MODEL, detect_family(DEFAULT_MODEL, "Auto"))
DEFAULT_UPSCALE = choose_choice(SCANS["upscalers"], ["4x-UltraSharp", "RealESRGAN_x4plus", "4xFaceUp"])
DEFAULT_CONTROLNET = choose_choice(SCANS["controlnets"], ["OpenPoseXL2", "openpose-xl", "openpose"])
DEFAULT_FAMILY = detect_family(DEFAULT_MODEL, "Auto")
DEFAULT_LORAS = compatible_lora_choices(SCANS["loras"], DEFAULT_FAMILY, False)


# ============================================================================
# UI
# ============================================================================

with gr.Blocks(title="BEAVIS — Local + RunPod") as demo:

    with gr.Row(equal_height=True, elem_id="one-row-toolbar", elem_classes=["compact-model-bar"]):
        model_dd = gr.Dropdown(choices=SCANS["models"], value=DEFAULT_MODEL, label="Model", scale=4, min_width=220, container=False)
        manual_models = gr.Checkbox(False, label="Manual", scale=0, min_width=108, container=False, elem_id="manual-toggle")
        generate_top = gr.Button("Generate", variant="primary", size="sm", scale=1)
        stop_top = gr.Button("Stop", variant="stop", size="sm", scale=1)
        status_toggle = gr.Button("Status", size="sm", scale=1)
        runpod_toggle = gr.Button("RunPod", size="sm", scale=1)
        queue_status = gr.Textbox(value="Queue: checking...", label="", interactive=False, container=False, scale=2, min_width=160, elem_id="queue-status")

    queue_timer = gr.Timer(value=3.0)
    with gr.Group(visible=False) as status_panel:
        with gr.Row():
            comfy_status = gr.Textbox(value=status_text(), label="ComfyUI Status", interactive=False, scale=3)
            refresh_status_btn = gr.Button("Refresh Status", scale=1)
            cancel_btn = gr.Button("Stop / Interrupt", variant="stop", scale=1)

    with gr.Group(visible=_runpod_needs_connection) as runpod_panel:
        gr.Markdown("Paste your current RunPod **ComfyUI proxy URL** ending in `-8188.proxy.runpod.net` (or another exposed ComfyUI URL), then connect. Saved pod addresses are not automatically reconnected when MUNG opens.")
        with gr.Row():
            remote_url = gr.Textbox(
            value="" if ("127.0.0.1" in COMFY_URL or "localhost" in COMFY_URL) else COMFY_URL,
            label="RunPod ComfyUI 8188 Proxy URL",
            placeholder="https://YOUR-POD-ID-8188.proxy.runpod.net",
            scale=4
        )
            connect_runpod_btn = gr.Button("Connect & Scan Pod Models", variant="primary", scale=1)

    with gr.Tabs(elem_id="main-tabs"):
        with gr.Tab("Generate / Edit"):
            with gr.Row():
                with gr.Column(scale=1, elem_classes=["beavis-resize"]):
                    with gr.Accordion("Manual settings — mode, loaders and sampling", open=True, visible=False) as manual_models_group:
                        mode = gr.Dropdown(MODES, value=SETTINGS.get("last_mode", "Auto"), label="Mode")
                        family_override = gr.Dropdown(FAMILY_OVERRIDES, value=SETTINGS.get("last_family_override", "Auto"), label="Model Family Override")
                        detected_family = gr.Textbox(value=DEFAULT_FAMILY, label="Detected Family", interactive=False)
                        gr.Markdown("### Text Encoder / VAE")
                        text_encoder_preset = gr.Radio(
                            ["Auto", "Official", "Uncensored", "Custom"], value="Auto", label="Klein Text Encoder Preset"
                        )
                        clip_dd = gr.Dropdown(choices=SCANS["clips"], value=DEFAULT_CLIP, label="Text Encoder")
                        vae_dd = gr.Dropdown(choices=SCANS["vaes"], value=DEFAULT_VAE, label="VAE")
                        flux_zero_negative = gr.Checkbox(
                            True,
                            label="FLUX.2 Klein: Use ConditioningZeroOut for negative (ignores Negative Prompt)",
                            info="ON = zero negative conditioning like the original Klein fallback. OFF = use the text Negative Prompt."
                        )

                        with gr.Row():
                            steps = gr.Slider(1, 50, value=6, step=1, label="Steps")
                            cfg = gr.Slider(0.5, 12.0, value=1.1, step=0.1, label="CFG")
                        with gr.Row():
                            sampler = gr.Dropdown(SAMPLERS, value="euler", label="Sampler")
                            scheduler = gr.Dropdown(SCHEDULERS, value="normal", label="Scheduler")
                        with gr.Row():
                            seed = gr.Number(value=-1, precision=0, label="Seed (-1 = random)")
                            seed_lock = gr.Checkbox(False, label="Lock seed after generation")
                            denoise = gr.Slider(0.05, 1.0, value=0.75, step=0.05, label="Denoise / Strength")


                    main_group = gr.Group(visible=True)
                    with main_group:
                        main_img = gr.Image(label="Main Image", type="pil", height=300)
                        reference_group = gr.Group(visible=True)
                        with reference_group:
                            reference_img = gr.Image(label="Reference Image (optional)", type="pil", height=220)
                            use_reference = gr.Checkbox(False, label="Use Reference Image")
                            gr.Markdown(
                                "**Reference prompt tip:** say exactly what to take from the reference — clothing, hairstyle, color, lighting, style, etc."
                            )

                    # Pose / OpenPose / ControlNet UI intentionally removed from the RunPod BEAVIS build.
                    # Hidden compatibility values keep the existing generation pipeline stable without exposing pose controls.
                    pose_img = gr.State(None)
                    use_controlnet = gr.State(False)
                    controlnet_dd = gr.Dropdown(choices=[], value=None, visible=False)
                    controlnet_strength = gr.State(0.85)
                    controlnet_start = gr.State(0.0)
                    controlnet_end = gr.State(1.0)

                    prompt = gr.Textbox(label="Prompt", lines=5, placeholder="Describe what to generate or change…")
                    prompt_history = gr.Dropdown(choices=list(_prompt_history), label="Last 5 Prompts", value=None)
                    negative_prompt = gr.Textbox(label="Negative Prompt", lines=2, placeholder="Things you want to avoid…")
                    upscale_group = gr.Group(visible=False)
                    with upscale_group:
                        gr.Markdown("### Upscale")
                        upscale_dd = gr.Dropdown(choices=SCANS["upscalers"], value=DEFAULT_UPSCALE, label="Upscale Model")
                        upscale_by = gr.Slider(1.0, 4.0, value=2.0, step=0.25, label="Upscale By")

                    with gr.Row():
                        refresh_models_btn = gr.Button("Refresh Models")
                        run_btn = gr.Button("Generate", variant="primary", size="lg")

                with gr.Column(scale=1, elem_classes=["beavis-resize"]):
                    output_img = gr.Image(label="Result", height=600)
                    with gr.Group(visible=False):
                        info = gr.Textbox(label="Generation Info", interactive=False, lines=3)
                    with gr.Accordion("My Notes", open=False):
                        personal_notes = gr.Textbox(label="My Notes", lines=6, placeholder="Type anything here...")

                    with gr.Accordion("LoRA Stack (3 slots)", open=False):
                        gr.Markdown("### LoRA Stack (serial order)")
                        use_lora = gr.Checkbox(False, label="Use LoRA 1")
                        show_all_loras = gr.Checkbox(False, label="Show all LoRAs (including possibly incompatible)")
                        lora_dd = gr.Dropdown(choices=DEFAULT_LORAS, value="", label="LoRA 1", interactive=False)
                        lora_strength = gr.Slider(0.0, 2.0, value=0.8, step=0.05, label="LoRA 1 Strength", interactive=False)
                        use_lora2 = gr.Checkbox(False, label="Use LoRA 2")
                        lora2_dd = gr.Dropdown(choices=DEFAULT_LORAS, value="", label="LoRA 2", interactive=False)
                        lora2_strength = gr.Slider(0.0, 2.0, value=0.7, step=0.05, label="LoRA 2 Strength", interactive=False)
                        use_lora3 = gr.Checkbox(False, label="Use LoRA 3")
                        lora3_dd = gr.Dropdown(choices=DEFAULT_LORAS, value="", label="LoRA 3", interactive=False)
                        lora3_strength = gr.Slider(0.0, 2.0, value=0.6, step=0.05, label="LoRA 3 Strength", interactive=False)


                    with gr.Group(visible=False):
                        use_lora_manager = gr.Checkbox(False, label="Use LoraManager Unlimited Stack")
                        lora_manager_table = gr.Dataframe(
                            headers=["Enabled", "LoRA", "Strength"],
                            datatype=["bool", "str", "number"],
                            value=[[False, "", 0.8], [False, "", 0.7], [False, "", 0.6]],
                            row_count=(3, "dynamic"), col_count=(3, "fixed"),
                            label="Add or remove rows; enter the LoRA filename/name",
                        )

                    gr.Markdown("### Output Resolution")
                    use_source = gr.Checkbox(True, label="Use Source Image Resolution")
                    preserve_aspect = gr.Checkbox(True, label="Preserve Source Aspect Ratio when using manual resolution")
                    with gr.Group(visible=False) as manual_res_group:
                        res_preset = gr.Dropdown(list(RES_PRESETS.keys()), value="1024 × 1024", label="Preset")
                        with gr.Row():
                            width = gr.Number(value=1024, precision=0, minimum=16, label="Width")
                            height = gr.Number(value=1024, precision=0, minimum=16, label="Height")

                    with gr.Accordion("Advanced Reference Scaling", open=False):
                        scale_method = gr.Dropdown(SCALE_METHODS, value="lanczos", label="Scaling Method")
                        scale_megapixels = gr.Slider(0.25, 4.0, value=2.0, step=0.25, label="Reference Megapixels")
                        resolution_steps = gr.Slider(1, 64, value=1, step=1, label="Resolution Steps")
                        gr.Markdown("Lanczos is the default here for photographic references. Resolution Steps affects resize granularity, not diffusion quality.")



                    with gr.Group(visible=False):
                        recommendation_box = gr.Textbox(
                            value=recommendations(DEFAULT_MODEL, DEFAULT_FAMILY, effective_mode("Auto", DEFAULT_FAMILY, False))["text"],
                            interactive=False, lines=8, label="Internal Model Recommendations"
                        )
                        apply_rec_btn = gr.Button("Apply Recommended Settings")
                        my_note = gr.Textbox(label="My Notes for This Model", lines=5)
                        save_note_btn = gr.Button("Save Model Note")
                        note_status = gr.Textbox(label="Note Status", interactive=False)


        with gr.Tab("WAN Image to Video"):
            gr.Markdown("### WAN 2.1 image to video\nUpload a starting image and describe its motion. Model names show the actual installed versions.")
            wan_models, wan_loras = wan21_choices()
            with gr.Row():
                with gr.Column():
                    wan_model = gr.Dropdown(wan_models, value=wan_models[0] if wan_models else None, label="WAN 2.1 I2V Model")
                    wan_image = gr.Image(label="Starting Image", type="pil", height=360)
                    wan_prompt = gr.Textbox(label="Motion Prompt", lines=3)
                    wan_negative = gr.Textbox(value="blurry, flicker, distorted, watermark, text", label="Negative Prompt", lines=2)
                    with gr.Row():
                        wan_width = gr.Number(value=832, precision=0, minimum=16, label="Video Width")
                        wan_height = gr.Number(value=480, precision=0, minimum=16, label="Video Height")
                    with gr.Row():
                        wan_frames = gr.Number(value=33, precision=0, minimum=5, label="Frames (17, 33, 49, 65, 81...)")
                        wan_fps = gr.Number(value=16, minimum=1, maximum=120, label="FPS")
                    with gr.Row():
                        wan_steps = gr.Slider(1, 100, value=20, step=1, label="Video Steps")
                        wan_cfg = gr.Slider(1, 15, value=6, step=.1, label="Video CFG")
                    with gr.Row():
                        wan_seed = gr.Number(value=123456789, precision=0, label="Video Seed (-1 = random)")
                        wan_shift = gr.Number(value=8, minimum=0, maximum=100, label="Sampling Shift")
                    wan_lora = gr.Dropdown(["None"] + wan_loras, value="None", label="Optional WAN LoRA")
                    wan_strength = gr.Slider(0, 2, value=.7, step=.05, label="WAN LoRA Strength")
                    with gr.Row():
                        wan_refresh = gr.Button("Refresh WAN Models")
                        wan_run = gr.Button("Generate Video", variant="primary")
                        wan_stop = gr.Button("Stop Video", variant="stop")
                with gr.Column():
                    wan_video = gr.Video(label="Generated Video")
                    wan_status = gr.Textbox(label="Video Status", interactive=False)
            wan_refresh.click(wan21_refresh, outputs=[wan_model, wan_lora, wan_status])
            wan_run.click(wan21_generate, inputs=[wan_model, wan_image, wan_prompt, wan_negative,
                wan_width, wan_height, wan_frames, wan_fps, wan_steps, wan_cfg, wan_seed,
                wan_shift, wan_lora, wan_strength], outputs=[wan_video, wan_status])
            wan_stop.click(cancel_generation, outputs=wan_status)


        with gr.Tab("ComfyUI Control"):
            gr.Markdown(
                "## ComfyUI Startup / Restart\n"
                "The GUI only stops/restarts a ComfyUI process that **it started itself**. It will not blindly kill other Python processes."
            )
            with gr.Row():
                comfy_python = gr.Textbox(value=SETTINGS.get("comfy_python"), label="Python Executable")
                comfy_main = gr.Textbox(value=SETTINGS.get("comfy_main"), label="ComfyUI main.py")
            comfy_output = gr.Textbox(value=SETTINGS.get("comfy_output"), label="ComfyUI Output Folder")

            with gr.Row():
                arg_windows = gr.Checkbox(SETTINGS.get("windows_standalone", True), label="--windows-standalone-build")
                arg_preview = gr.Checkbox(SETTINGS.get("preview_none", True), label="--preview-method none")
                arg_fast_disk = gr.Checkbox(SETTINGS.get("fast_disk", True), label="--fast-disk")
            with gr.Row():
                auto_fp8 = gr.Checkbox(SETTINGS.get("auto_fp8", True), label="Auto FP8 (only when filename says FP8)")
                arg_fp8_unet = gr.Checkbox(SETTINGS.get("fp8_unet", False), label="--fp8_e4m3fn-unet (manual)")
                arg_fp8_text = gr.Checkbox(SETTINGS.get("fp8_text", False), label="--fp8_e4m3fn-text-enc (manual)")
            extra_args = gr.Textbox(value=SETTINGS.get("extra_args", ""), label="Extra Arguments", placeholder="Any extra ComfyUI flags…")
            launch_preview = gr.Textbox(label="Launch Command Preview", interactive=False, lines=3)

            with gr.Row():
                save_startup_btn = gr.Button("Save Startup Settings")
                start_comfy_btn = gr.Button("Start ComfyUI", variant="primary")
                restart_comfy_btn = gr.Button("Restart ComfyUI")
                open_output_btn = gr.Button("Open Output Folder")
            comfy_control_info = gr.Textbox(label="ComfyUI Control Info", interactive=False)
            with gr.Row():
                refresh_log_btn = gr.Button("Refresh Log")
            comfy_log_box = gr.Textbox(label="ComfyUI Log (GUI-owned process)", lines=20, interactive=False, value=log_text())

    # ---------------- Events ----------------
    status_open = gr.State(False)
    runpod_open = gr.State(_runpod_needs_connection)
    def toggle_panel(opened):
        opened = not opened
        return opened, gr.update(visible=opened)
    status_toggle.click(toggle_panel, inputs=status_open, outputs=[status_open, status_panel])
    runpod_toggle.click(toggle_panel, inputs=runpod_open, outputs=[runpod_open, runpod_panel])
    manual_models.change(lambda checked: gr.update(visible=checked), inputs=manual_models, outputs=manual_models_group)
    refresh_status_btn.click(status_text, outputs=comfy_status)
    queue_timer.tick(queue_status_text, outputs=queue_status, show_progress="hidden")
    demo.load(queue_status_text, outputs=queue_status)
    cancel_btn.click(cancel_generation, outputs=info)

    use_lora.change(on_lora_toggle, inputs=use_lora, outputs=[lora_dd, lora_strength])
    use_lora2.change(on_lora_toggle, inputs=use_lora2, outputs=[lora2_dd, lora2_strength])
    use_lora3.change(on_lora_toggle, inputs=use_lora3, outputs=[lora3_dd, lora3_strength])
    text_encoder_preset.change(on_text_preset, inputs=[text_encoder_preset, clip_dd], outputs=clip_dd)
    mode.change(on_mode_change, inputs=mode, outputs=[main_group, reference_group, negative_prompt, use_source, upscale_group])
    use_source.change(on_use_source, inputs=[use_source, main_img], outputs=[manual_res_group, width, height, res_preset])
    width.change(on_width_change, inputs=[width, preserve_aspect, main_img], outputs=height)
    preserve_aspect.change(on_width_change, inputs=[width, preserve_aspect, main_img], outputs=height)
    res_preset.change(apply_preset, inputs=res_preset, outputs=[width, height])
    prompt_history.change(use_prompt_history, inputs=prompt_history, outputs=prompt)

    model_dd.change(
        on_model_change,
        inputs=[model_dd, family_override, mode, show_all_loras, text_encoder_preset, clip_dd],
        outputs=[detected_family, recommendation_box, lora_dd, lora2_dd, lora3_dd, clip_dd, vae_dd, my_note],
    )
    family_override.change(
        on_model_change,
        inputs=[model_dd, family_override, mode, show_all_loras, text_encoder_preset, clip_dd],
        outputs=[detected_family, recommendation_box, lora_dd, lora2_dd, lora3_dd, clip_dd, vae_dd, my_note],
    )
    show_all_loras.change(
        on_model_change,
        inputs=[model_dd, family_override, mode, show_all_loras, text_encoder_preset, clip_dd],
        outputs=[detected_family, recommendation_box, lora_dd, lora2_dd, lora3_dd, clip_dd, vae_dd, my_note],
    )

    apply_rec_btn.click(
        apply_recommended,
        inputs=[model_dd, family_override, mode, main_img],
        outputs=[sampler, scheduler, steps, cfg, denoise],
    )
    save_note_btn.click(save_model_note, inputs=[model_dd, my_note], outputs=note_status)

    refresh_models_btn.click(
        refresh_models_ui,
        inputs=[family_override, model_dd, show_all_loras],
        outputs=[model_dd, clip_dd, vae_dd, lora_dd, lora2_dd, lora3_dd, upscale_dd, controlnet_dd, info],
    )
    connect_runpod_btn.click(
        connect_runpod_and_scan,
        inputs=[remote_url, family_override, model_dd, show_all_loras],
        outputs=[model_dd, clip_dd, vae_dd, lora_dd, lora2_dd, lora3_dd, upscale_dd, controlnet_dd, info, comfy_status],
    )

    run_btn.click(
        generate,
        inputs=[
            mode, family_override,
            model_dd, clip_dd, vae_dd, upscale_dd,
            text_encoder_preset,
            main_img, reference_img, use_reference,
            pose_img, use_controlnet, controlnet_dd,
            controlnet_strength, controlnet_start, controlnet_end,
            prompt, negative_prompt, flux_zero_negative,
            use_lora, lora_dd, lora_strength,
            use_lora2, lora2_dd, lora2_strength,
            use_lora3, lora3_dd, lora3_strength,
            use_lora_manager, lora_manager_table,
            steps, cfg, seed, denoise, sampler, scheduler,
            use_source, preserve_aspect, width, height,
            scale_method, scale_megapixels, resolution_steps,
            upscale_by, seed_lock,
        ],
        outputs=[output_img, info, prompt_history, seed],
    )

    # Startup command preview updates.
    launch_inputs = [
        comfy_python, comfy_main, arg_windows, arg_preview, arg_fast_disk,
        auto_fp8, arg_fp8_unet, arg_fp8_text, extra_args, model_dd, clip_dd,
    ]
    for comp in launch_inputs:
        comp.change(command_preview, inputs=launch_inputs, outputs=launch_preview)

    save_startup_btn.click(
        save_startup_settings,
        inputs=[comfy_python, comfy_main, comfy_output, arg_windows, arg_preview, arg_fast_disk, auto_fp8, arg_fp8_unet, arg_fp8_text, extra_args],
        outputs=comfy_control_info,
    )
    start_comfy_btn.click(start_comfy, inputs=launch_inputs, outputs=comfy_control_info)
    restart_comfy_btn.click(restart_comfy, inputs=launch_inputs, outputs=comfy_control_info)
    open_output_btn.click(open_output_folder, inputs=comfy_output, outputs=comfy_control_info)
    refresh_log_btn.click(log_text, outputs=comfy_log_box)

    demo.load(command_preview, inputs=launch_inputs, outputs=launch_preview)
    demo.load(status_text, outputs=comfy_status)

    # These two top-bar controls proxy the visible Generate and Stop buttons.
    # Event handlers must be registered while the Blocks context is still open.
    generate_top.click(
        fn=None,
        js="""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const target = buttons.find(b => b.textContent.trim() === 'Generate' && !b.disabled && b.offsetParent !== null && b !== document.activeElement);
            if (target) target.click();
        }"""
    )
    stop_top.click(
        fn=None,
        js="""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const targets = buttons.filter(b => b.textContent.includes('Stop / Interrupt') && b.offsetParent !== null);
            if (targets.length) targets[targets.length - 1].click();
        }"""
    )


def find_free_gui_port(start_port=7860, end_port=7899):
    """Return the first free localhost TCP port in the requested range."""
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError(f"No free GUI port found in range {start_port}-{end_port}")


if __name__ == "__main__":
    print("Universal ComfyUI GUI")
    print(f"Models: {len(SCANS['models'])} | Encoders: {len(SCANS['clips'])} | VAEs: {len(SCANS['vaes'])} | LoRAs: {len(SCANS['loras'])} | Upscalers: {len(SCANS['upscalers'])}")
    print(f"ComfyUI: {COMFY_URL}")
    gui_port = find_free_gui_port()
    print(f"GUI: http://127.0.0.1:{gui_port}")
    if gui_port != 7860:
        print(f"Port 7860 is busy, automatically using {gui_port} instead.")
    demo.queue().launch(
        server_name="127.0.0.1",
        server_port=gui_port,
        inbrowser=(os.name == "nt"),
        theme=gr.themes.Soft(),
        css=".beavis-resize {resize:none!important;overflow:visible!important;} #one-row-toolbar {gap:6px!important;align-items:center!important;margin:0!important;padding:0 0 0 175px!important;flex-wrap:nowrap!important;} #manual-toggle {flex:0 0 108px!important;min-width:108px!important;max-width:108px!important;overflow:visible!important;background:#353f50!important;border:1px solid #596579!important;border-radius:8px!important;padding:0 10px!important;min-height:38px!important;display:flex!important;align-items:center!important;justify-content:center!important;} #manual-toggle label {white-space:nowrap!important;overflow:visible!important;font-weight:600!important;cursor:pointer!important;} #manual-toggle input {accent-color:#6554ed!important;} #one-row-toolbar > div {min-width:0!important;margin:0!important;} #one-row-toolbar .gradio-accordion {flex:0 0 100px!important;} #one-row-toolbar .gradio-accordion > button {white-space:nowrap!important;} #main-tabs .tab-nav {position:relative!important;margin-top:-52px!important;margin-bottom:18px!important;width:max-content!important;z-index:5!important;} #main-tabs {margin-top:0!important;} ",
    )
