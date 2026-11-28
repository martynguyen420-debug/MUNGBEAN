"""
MUNGPOD RunPod GUI ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Local Edition

Designed to run inside each RunPod pod beside that pod's ComfyUI.

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

import asyncio
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

import aiohttp
import gradio as gr
import requests
import uuid
from PIL import Image
import socket

# ============================================================================
# CONFIG
# ============================================================================

APP_DIR = Path(__file__).resolve().parent

def _discover_comfy_root() -> Path:
    configured = os.environ.get("COMFY_ROOT")
    if configured:
        return Path(configured).expanduser()
    candidates = [
        Path("/workspace/runpod-slim/ComfyUI"),
        Path("/workspace/ComfyUI"),
        Path("/workspace-global/runpod-slim/ComfyUI"),
        Path("/workspace-global/ComfyUI"),
    ]
    return next((candidate for candidate in candidates if (candidate / "main.py").is_file()), candidates[0])

COMFY_ROOT = _discover_comfy_root()
SETTINGS_FILE = APP_DIR / "mungpod_settings.json"
COMFY_URL = (os.environ.get("COMFY_URL") or "http://127.0.0.1:8188").rstrip("/")
DEFAULT_COMFY_ROOT = COMFY_ROOT
DEFAULT_COMFY_MAIN = Path(os.environ.get("COMFY_MAIN", str(COMFY_ROOT / "main.py")))
DEFAULT_COMFY_PYTHON = Path(os.environ.get("COMFY_PYTHON", str(COMFY_ROOT / ".venv-cu128" / "bin" / "python")))
DEFAULT_COMFY_OUTPUT = Path(os.environ.get("COMFY_OUTPUT", str(COMFY_ROOT / "output")))

def _discover_model_roots() -> List[Path]:
    candidates = [COMFY_ROOT / "models"]
    configured = os.environ.get("MUNGPOD_MODEL_ROOTS", "")
    candidates.extend(Path(p).expanduser() for p in configured.split(os.pathsep) if p.strip())
    candidates.extend([
        Path("/workspace/runpod-slim/ComfyUI/models"),
        Path("/workspace/ComfyUI/models"),
        Path("/workspace-global/runpod-slim/ComfyUI/models"),
        Path("/workspace-global/ComfyUI/models"),
    ])
    roots, seen = [], set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve()).casefold()
        except OSError:
            key = str(candidate).casefold()
        if key not in seen and candidate.is_dir():
            seen.add(key)
            roots.append(candidate)
    if not roots:
        roots = [COMFY_ROOT / "models"]
    return roots

MODEL_ROOTS = _discover_model_roots()
EXTRA_LORA_DIRS = [
    Path(p).expanduser()
    for p in os.environ.get("MUNGPOD_EXTRA_LORA_DIRS", "").split(os.pathsep)
    if p.strip()
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
    "512 ÃƒÆ’Ã¢â‚¬â€ 512": (512, 512),
    "768 ÃƒÆ’Ã¢â‚¬â€ 768": (768, 768),
    "1024 ÃƒÆ’Ã¢â‚¬â€ 1024": (1024, 1024),
    "1280 ÃƒÆ’Ã¢â‚¬â€ 704 (Qwen)": (1280, 704),
    "1280 ÃƒÆ’Ã¢â‚¬â€ 720 (HD)": (1280, 720),
    "1920 x 1080 (FHD)": (1920, 1080),
    "2560 x 1440 (QHD)": (2560, 1440),
    "1440 x 2560 (Portrait)": (1440, 2560),
    "2048 x 2048": (2048, 2048),
    "3840 x 2160 (4K)": (3840, 2160),
    "2160 x 3840 (Portrait 4K)": (2160, 3840),
    "832 ÃƒÆ’Ã¢â‚¬â€ 1216 (Portrait)": (832, 1216),
    "1216 ÃƒÆ’Ã¢â‚¬â€ 832 (Landscape)": (1216, 832),
}

MODES = [
    "Auto",
    "FLUX.2 Klein - Image Edit",
    "FLUX.2 Klein - Image Generate",
    "FLUX 3 - Image Edit",
    "FLUX 3 - Image Generate",
    "Qwen Rapid - Image Edit",
    "Qwen Rapid - Image Generate",
    "Qwen Image 2.1 Turbo - Image Generate",
    "Qwen Image 2.1 Turbo - Image Edit",
    "WAN 2.2 Rapid AIO - Text to Image",
    "WAN 2.2 Rapid AIO - Image Edit",
    "MOSS - Image Generate",
    "MOSS - Image Edit",
    "Krea - Image Edit",
    "Krea - Image Generate",
    "Checkpoint - Generate",
    "Checkpoint - Img2Img",
    "Standard Model Upscale",
    "Ultimate SD Upscale",
]

FAMILY_OVERRIDES = ["Auto", "FLUX 3", "FLUX.2 Klein", "Qwen Rapid", "Qwen Image 2.1 Turbo", "WAN 2.2 Rapid AIO", "MOSS", "SDXL / Pony", "SD1.5", "Checkpoint / Unknown"]

SAMPLERS = [
    "euler", "euler_ancestral", "heun", "lms", "dpm_2", "dpm_2_ancestral",
    "dpmpp_2s_ancestral", "dpmpp_2m", "dpmpp_sde", "dpmpp_2m_sde",
    "dpmpp_3m_sde_gpu", "lcm",
]
SCHEDULERS = ["normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform", "beta"]
SCALE_METHODS = ["lanczos", "bicubic", "bilinear", "nearest-exact", "area"]

_current_prompt_id: Optional[str] = None
_cancel_requested = False
_owned_comfy_process: Optional[subprocess.Popen] = None
_comfy_log: deque[str] = deque(maxlen=250)
_object_info_cache: Optional[Dict[str, Any]] = None
_live_console_lock = threading.RLock()
_live_console_lines: deque[str] = deque(maxlen=9)
_live_console_status = "Ready. Waiting for Generate."
_live_console_started_at: Optional[float] = None


def live_console_text() -> str:
    with _live_console_lock:
        lines = list(_live_console_lines)
        status = _live_console_status
        started = _live_console_started_at
    if started is not None and "s elapsed" not in status:
        status = f"{status} | {int(time.time() - started)}s elapsed"
    lines.append(status)
    return "\n".join(lines)


def live_console_begin(message: str) -> None:
    global _live_console_started_at, _live_console_status
    with _live_console_lock:
        _live_console_lines.clear()
        _live_console_started_at = time.time()
        _live_console_status = message
        _live_console_lines.append(time.strftime("%H:%M:%S") + " | " + message)


def live_console_log(message: str) -> None:
    global _live_console_status
    with _live_console_lock:
        _live_console_lines.append(time.strftime("%H:%M:%S") + " | " + message)
        _live_console_status = message


def live_console_set_status(message: str) -> None:
    global _live_console_status
    with _live_console_lock:
        _live_console_status = message


def live_console_finish(message: str) -> None:
    global _live_console_started_at, _live_console_status
    with _live_console_lock:
        elapsed = int(time.time() - _live_console_started_at) if _live_console_started_at else 0
        _live_console_lines.append(time.strftime("%H:%M:%S") + f" | {message} ({elapsed}s)")
        _live_console_started_at = None
        _live_console_status = message


def _comfy_progress_listener(client_id: str, prompt_id: str, node_map: Dict[str, str], stop_event: threading.Event, ready_event: threading.Event) -> None:
    async def listen() -> None:
        ws_url = COMFY_URL.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        ws_url += f"/ws?clientId={client_id}"
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(ws_url, heartbeat=20, timeout=10) as ws:
                ready_event.set()
                live_console_log("Live connection to ComfyUI established")
                while not stop_event.is_set():
                    try:
                        message = await ws.receive(timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if message.type == aiohttp.WSMsgType.TEXT:
                        try:
                            event = json.loads(message.data)
                        except (TypeError, ValueError):
                            continue
                        event_type = event.get("type", "")
                        data = event.get("data") or {}
                        event_prompt = data.get("prompt_id") if isinstance(data, dict) else None
                        if event_prompt and prompt_id and event_prompt != prompt_id:
                            continue
                        if event_type == "execution_start":
                            live_console_log("ComfyUI started the workflow")
                        elif event_type == "executing" and isinstance(data, dict):
                            node_id = data.get("node")
                            if node_id is None:
                                live_console_log("ComfyUI finished the node graph; waiting for saved output")
                            else:
                                label = node_map.get(str(node_id), str(node_id))
                                live_console_log(f"ComfyUI running {label} (node {node_id})")
                        elif event_type == "progress" and isinstance(data, dict):
                            value = data.get("value")
                            maximum = data.get("max")
                            node_id = data.get("node")
                            label = node_map.get(str(node_id), "sampling") if node_id is not None else "sampling"
                            if value is not None and maximum is not None:
                                live_console_log(f"Step {value}/{maximum} | {label}")
                        elif event_type == "execution_cached" and isinstance(data, dict):
                            cached = data.get("nodes") or []
                            if cached:
                                live_console_log(f"ComfyUI reused {len(cached)} cached node(s)")
                        elif event_type == "execution_error" and isinstance(data, dict):
                            detail = data.get("exception_message") or "ComfyUI reported an execution error"
                            live_console_log("ERROR | " + str(detail).splitlines()[0])
                        elif event_type == "execution_success":
                            live_console_log("ComfyUI finished; retrieving output")
                    elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        break
    async def runner() -> None:
        try:
            await listen()
        except Exception as exc:
            live_console_log("Live step feed unavailable: " + str(exc).splitlines()[0])
        finally:
            ready_event.set()
    try:
        asyncio.run(runner())
    except Exception as exc:
        ready_event.set()
        live_console_log("Live step feed unavailable: " + str(exc).splitlines()[0])



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
        "windows_standalone": False,
        "preview_none": True,
        "fast_disk": False,
        "auto_fp8": False,
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


SETTINGS = load_settings()
COMFY_URL = (os.environ.get("COMFY_URL") or SETTINGS.get("comfy_url") or COMFY_URL).rstrip("/")
MODEL_SOURCE = "runpod"
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
                label = Path(rel).name
                if sub.casefold() in ("checkpoints", "unet", "diffusion_models") and "lora" in label.casefold():
                    continue
                if (
                    sub.casefold() == "diffusion_models"
                    and label.casefold().startswith("wan2.2-rapid-mega-aio")
                    and any(
                        choice_category(value).casefold() == "checkpoints"
                        and Path(_decode_choice(value)[1]).name.casefold() == label.casefold()
                        for _existing_label, value in buckets["models"]
                    )
                ):
                    continue
                key = (sub.casefold(), label.casefold())
                if key in seen[bucket]:
                    continue
                seen[bucket].add(key)
                label = Path(rel).name
                buckets[bucket].append((label, _encode_choice(sub, rel, idx)))

        # C:\\ai stores these FLUX.2 Klein diffusion weights directly at its root.
        if str(root).casefold() == r"c:\ai":
            try:
                direct_models = [
                    path for path in root.iterdir()
                    if path.is_file() and path.name.casefold().endswith(MODEL_EXTS)
                ]
            except (PermissionError, OSError):
                direct_models = []
            for path in direct_models:
                label = path.name
                if "lora" in label.casefold():
                    continue
                key = ("diffusion_models", label.casefold())
                if key not in seen["models"]:
                    seen["models"].add(key)
                    buckets["models"].append(
                        (label, _encode_choice("diffusion_models", label, idx))
                    )
    # A few MOSS releases are duplicated under checkpoints and diffusion_models.
    # Keep the valid diffusion-model entry only so MUNGON cannot route the copy
    # through CheckpointLoaderSimple by accident.
    moss_diffusion_names = {
        Path(_decode_choice(value)[1]).name.casefold()
        for label, value in buckets["models"]
        if "moss" in label.casefold() and choice_category(value) in ("unet", "diffusion_models")
    }
    if moss_diffusion_names:
        buckets["models"] = [
            (label, value) for label, value in buckets["models"]
            if not (
                choice_category(value) == "checkpoints"
                and Path(_decode_choice(value)[1]).name.casefold() in moss_diffusion_names
            )
        ]

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
    """Read available models from the fixed local ComfyUI API only."""
    try:
        data = requests.get(f"{COMFY_URL}/object_info", timeout=4).json()
        names = data.get(node_name, {}).get("input", {}).get("required", {}).get(input_name, [[]])[0]
        return names if isinstance(names, list) else []
    except Exception:
        return []

def current_scans() -> Dict[str, List[Tuple[str, str]]]:
    return scan_all_models()

def choice_rel(value: Optional[str]) -> str:
    return _decode_choice(value)[1]


def choice_category(value: Optional[str]) -> str:
    return _decode_choice(value)[0]


def choose_choice(choices: List[Tuple[str, str]], needles: List[str]) -> Optional[str]:
    for needle in needles:
        for label, value in choices:
            if "mmproj" in label.casefold():
                continue
            if needle.casefold() in label.casefold():
                return value
    for label, value in choices:
        if "mmproj" not in label.casefold():
            return value
    return None


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
    if "moss" in s:
        return "MOSS"
    if "qwen-image-2.1-turbo" in s or "qwen_image_2.1_turbo" in s:
        return "Qwen Image 2.1 Turbo"
    if "qwen" in s and ("rapid" in s or "phroot" in s or "phr00t" in s):
        return "Qwen Rapid"
    if "aisha" in s and "qwen" in s and "turbo" in s:
        return "Qwen Image 2.1 Turbo"
    if "wan2.2" in s and "rapid" in s and "aio" in s:
        return "WAN 2.2 Rapid AIO"
    if "aisha" in s:
        return "FLUX.2 Klein"
    if "krea" in s or "kreanoct" in s:
        return "Krea 2"
    if "flux3" in s or "flux-3" in s or "flux_3" in s:
        return "FLUX 3"
    if any(token in s for token in ("mopmixtureofperverts", "mixture-of-perverts", "biglustydonut")):
        return "SDXL / Pony"
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
    # The 18 GB BF16 Klein 9B SNOFS file has no explicit 9B token in its filename.
    return "9b" in name or "9-b" in name or "aisha" in name or "snofs_1_4_kleindistilled" in name


def is_model_only_flux_file(model_value: Optional[str]) -> bool:
    """True for FLUX/Klein weights stored under checkpoints without CLIP/VAE.

    ComfyUI accepts these through CheckpointLoaderSimple, then falls back to a
    diffusion-model-only load.  Its CLIP and VAE outputs are None, so the
    caller must add separate loaders for those components.
    """
    _cat, rel, _ = _decode_choice(model_value) if model_value else ("", "", 0)
    low = rel.casefold()
    return (
        "aisha" in low
        or "flux2klein" in low
        or "flux-2-klein" in low
        or ("snofs" in low and "klein" in low)
    )


def effective_mode(mode: str, family: str, has_main: bool) -> str:
    """Source image takes priority over stale manual generate/edit selections.

    Explicit upscale operations are not generation and remain available.
    """
    if mode in ("Standard Model Upscale", "Ultimate SD Upscale"):
        return mode
    if family == "MOSS":
        return "MOSS - Image Edit" if has_main else "MOSS - Image Generate"
    if family == "Qwen Image 2.1 Turbo":
        return "Qwen Image 2.1 Turbo - Image Edit" if has_main else "Qwen Image 2.1 Turbo - Image Generate"
    if family == "WAN 2.2 Rapid AIO":
        return "WAN 2.2 Rapid AIO - Image Edit" if has_main else "WAN 2.2 Rapid AIO - Text to Image"
    if family == "Qwen Rapid":
        return "Qwen Rapid - Image Edit" if has_main else "Qwen Rapid - Image Generate"
    if family == "Krea 2":
        return "Krea - Image Edit" if has_main else "Krea - Image Generate"
    if family == "FLUX 3":
        return "FLUX 3 - Image Edit" if has_main else "FLUX 3 - Image Generate"
    if family == "FLUX.2 Klein":
        return "FLUX.2 Klein - Image Edit" if has_main else "FLUX.2 Klein - Image Generate"
    return "Checkpoint - Img2Img" if has_main else "Checkpoint - Generate"


def recommendations(model_value: Optional[str], family: str, mode: str) -> Dict[str, Any]:
    name = choice_rel(model_value)
    low = name.casefold()
    if family == "MOSS":
        is_edit = "Edit" in mode
        is_turbo = "turbo" in low or "dmd2" in low
        if is_turbo:
            return {"sampler":"euler_ancestral", "scheduler":"simple", "steps":6, "cfg":1.0,
                    "denoise":0.55 if is_edit else 1.0,
                    "text":"Juggernaut Moss Turbo: 6 steps, Euler Ancestral, Simple, CFG 1. The DMD2 turbo weights are baked into this model; no separate LoRA is needed. Negative prompting has no effect at CFG 1."}
        return {"sampler":"euler", "scheduler":"sgm_uniform", "steps":50, "cfg":3.0,
                "denoise":0.55 if is_edit else 1.0,
                "text":"MOSS Base: Euler, SGM Uniform, 50 steps, CFG 3. Img2img denoise 0.55. Requires a MOSS loader, moss_image text encoder, Flux2 VAE, and Skip Layer Guidance node."}
    if family == "Qwen Image 2.1 Turbo":
        return {"sampler":"euler", "scheduler":"simple", "steps":8, "cfg":1.0, "denoise":1.0,
                "text":"Qwen Image 2.1 Turbo: 8 fixed sigma steps, Euler, CFG 1.0; dedicated sampler. Negative prompt is ignored at CFG 1.0."}
    if family == "WAN 2.2 Rapid AIO":
        return {"sampler":"dpmpp_sde", "scheduler":"beta", "steps":4, "cfg":1.0, "denoise":1.0,
                "text":"WAN 2.2 Rapid AIO: 4 steps, DPM++ SDE, Beta, CFG 1. A source image creates a single edited frame; with no source, MUNGON makes a single text-conditioned frame."}
    if family == "Krea 2":
        # Known 8-step edit merge; other Krea2 weights use a conservative low-step starting profile.
        krea_steps = 8 if "snofs" in low and "edit" in low else 12
        return {"sampler": "euler", "scheduler": "simple", "steps": krea_steps,
                "cfg": 1.0, "denoise": 1.0,
                "text": f"KREA 2 {name}: low-step starting profile, {krea_steps} steps, Euler, Simple, CFG 1.0."}
    if family == "FLUX.2 Klein":
        is_9b = is_klein_9b(model_value)
        is_aisha = "aisha" in low
        steps = 12 if is_aisha else (4 if is_9b else (6 if "base" not in low else 12))
        cfg = 1.1 if is_aisha else (1.0 if is_9b else 1.1)
        return {
            "sampler": "euler",
            "scheduler": "normal",
            "steps": steps,
            "cfg": cfg,
            "denoise": 1.0,
            "text": (
                f"Model: {name or '(not selected)'}\n"
                f"Family: FLUX.2 Klein{' Ãƒâ€šÃ‚Â· 9B' if is_9b else ''}{' Ãƒâ€šÃ‚Â· Aisha' if is_aisha else ''}\n"
                f"Starting point: Euler ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ CFG {cfg} ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ {steps} steps.\n"
                "Edit denoise: try 0.65ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“0.85; Generate denoise: 1.0.\n"
                "Auto-selects flux2-vae + matching Qwen text encoder.\n"
                "9B LoRAs only on 9B models; 4B LoRAs only on 4B (stack validated before queue)."
            )
        }
    if family == "FLUX 3":
        return {"sampler": "euler", "scheduler": "simple", "steps": 8, "cfg": 1.0, "denoise": 1.0,
                "text": "FLUX 3 Klein: Euler, simple, 8 steps, CFG 1.0. Uses Qwen3-VL 4B encoder and flux2-vae."}
    if family == "Qwen Rapid":
        return {
            "sampler": "euler_ancestral", "scheduler": "beta", "steps": 4, "cfg": 1.2, "denoise": 1.0,
            "text": (
                f"Model: {name or '(not selected)'}\nFamily: Qwen Rapid / Phr00t\n"
                "Starting point: Euler Ancestral ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ Beta ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ 4 steps ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ CFG 1.2.\n"
                "Use a reference image for edit mode. Auto-picks Qwen VL encoder when present."
            )
        }
    if family == "SDXL / Pony" and "mopmixtureofperverts" in low:
        is_edit = "img2img" in mode.casefold()
        return {
            "sampler": "lcm", "scheduler": "karras", "steps": 9, "cfg": 1.0,
            "denoise": 0.65 if is_edit else 1.0,
            "text": "Mixture of Perverts v5.1 DMD SDXL: 9 steps, LCM, Karras, CFG 1.0. For img2img, start near 0.65 denoise; adjust from 0.5 to 0.8.",
        }
    if family == "SDXL / Pony" and "biglustydonut" in low:
        is_edit = "img2img" in mode.casefold()
        return {
            "sampler": "dpmpp_3m_sde_gpu", "scheduler": "karras", "steps": 30, "cfg": 2.0,
            "denoise": 0.65 if is_edit else 1.0,
            "text": "BigLustyDonutMix v1.2 SDXL: 30 steps, DPM++ 3M SDE GPU, Karras, CFG 2.0. For img2img, start near 0.65 denoise.",
        }
    if family == "SDXL / Pony":
        return {
            "sampler": "dpmpp_sde", "scheduler": "karras", "steps": 20, "cfg": 7.0, "denoise": 1.0,
            "text": (
                f"Model: {name or '(not selected)'}\nFamily: SDXL / Pony\n"
                "Your supplied Pony workflow uses DPM++ SDE ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ Karras ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ 30 steps ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ CFG 8.3.\n"
                "Treat that as a starting profile; individual Pony/SDXL checkpoints may prefer different CFG."
            )
        }
    if family == "SD1.5":
        return {
            "sampler": "dpmpp_2m", "scheduler": "karras", "steps": 18, "cfg": 7.0, "denoise": 1.0,
            "text": (
                f"Model: {name or '(not selected)'}\nFamily: SD1.5\n"
                "General starting profile: DPM++ 2M ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ Karras ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ 25 steps ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ CFG 7.\n"
                "For img2img, lower denoise preserves more of the source."
            )
        }
    return {
        "sampler": "euler", "scheduler": "normal", "steps": 20, "cfg": 7.0, "denoise": 1.0,
        "text": f"Model: {name or '(not selected)'}\nFamily: {family}\nUse the family override if auto-detection is wrong."
    }


def compatible_lora_choices(all_loras: List[Tuple[str, str]], family: str, show_all: bool) -> List[Tuple[str, str]]:
    none = [("None", "")]
    if family == "MOSS":
        return none
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
      - 9B model ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ prefer qwen_3_8b / 8b flux2 encoders when present
      - 4B model ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ prefer qwen_3_4b / 4b encoders
      - Uncensored preset ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ abl/uncensored GGUF variants
    """
    if preset == "Custom":
        return current
    if preset == "Uncensored" and not (model_value and detect_family(model_value, "Auto") == "MOSS"):
        return choose_choice(clips, [
            "qwen3-4b-abl", "abl", "uncensored",
            "flux2-klein-4b-uncensored", "flux2-klein-9b-uncensored",
        ])
    if model_value and detect_family(model_value, "Auto") == "Qwen Rapid":
        picked = choose_choice(clips, ["Qwen2.5-VL-7B-Instruct-Q8_0.gguf", "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "qwen2.5-vl"])
        if not picked or "qwen2.5-vl" not in choice_rel(picked).casefold() or "mmproj" in choice_rel(picked).casefold():
            raise ValueError("Qwen Rapid requires a Qwen2.5-VL text encoder; none found")
        return picked
    if model_value and detect_family(model_value, "Auto") == "MOSS":
        model_rel = choice_rel(model_value).casefold()
        moss_needles = (["qwen3.5-9b-q4_k_m.gguf", "qwen3.5-9b"]
                        if model_rel.endswith(".gguf")
                        else ["qwen3.5_9b_int8_convrot.safetensors",
                              "qwen3.5_9b_w4a8_gptq.safetensors", "qwen3.5"])
        return next((value for needle in moss_needles
                     for label, value in clips if needle in label.casefold()), None)
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
    if family == "MOSS":
        return choose_choice(vaes, ["flux2-vae.safetensors", "flux2-vae"])
    model_name = choice_rel(model_value).casefold() if model_value else ""
    is_qwen_aisha_turbo = "aisha" in model_name and "qwen" in model_name and "turbo" in model_name
    if family == "FLUX.2 Klein" or ("aisha" in model_name and not is_qwen_aisha_turbo):
        return choose_choice(vaes, ["flux2-vae", "flux2", "ae.safetensors"])
    if family == "Qwen Image 2.1 Turbo":
        return choose_choice(vaes, ["qwen_image_2.1_vae_bf16"])
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

    - GGUF ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ UnetLoaderGGUF
    - Checkpoint (incl. big Aisha) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ CheckpointLoaderSimple (MODEL+CLIP+VAE)
    - Otherwise ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ UNETLoader
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
    clip_type = "moss_image" if family == "MOSS" else ("flux3" if "qwen3vl" in choice_rel(clip_value).casefold() else ("flux2" if family == "FLUX.2 Klein" else "qwen_image"))
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



def build_flux3_prompt(model_value, prompt_text, negative_text, clip_value, vae_value,
                       main_name, ref_name, use_reference, steps, cfg, seed, denoise,
                       width, height, sampler, scheduler, scale_megapixels):
    """FLUX 3 graph from verified ComfyUI PNG metadata, with optional 2 references."""
    model=choice_rel(model_value)
    clip=choose_choice(SCANS["clips"], ["qwen3vl_4b_fp8_scaled", "qwen3vl_4b_int8", "qwen3vl_4b"])
    vae=choose_choice(SCANS["vaes"], ["flux2-vae"])
    if not clip or "qwen3vl_4b" not in choice_rel(clip).casefold():
        raise gr.Error("FLUX 3 needs qwen3vl_4b text encoder. Put it in models/text_encoders and Refresh Models.")
    if not vae or "flux2-vae" not in choice_rel(vae).casefold():
        raise gr.Error("FLUX 3 needs flux2-vae.safetensors in models/vae.")
    p={
      "1":{"class_type":"UNETLoader","inputs":{"unet_name":model,"weight_dtype":"default"}},
      "2":{"class_type":"CLIPLoader","inputs":{"clip_name":choice_rel(clip),"type":"flux3","device":"default"}},
      "3":{"class_type":"VAELoader","inputs":{"vae_name":choice_rel(vae)}},
      "4":{"class_type":"CLIPTextEncode","inputs":{"clip":["2",0],"text":prompt_text}},
      "5":{"class_type":"CLIPTextEncode","inputs":{"clip":["2",0],"text":negative_text or ""}},
      "7":{"class_type":"KSampler","inputs":{"seed":int(seed),"steps":int(steps),"cfg":float(cfg),
           "sampler_name":sampler,"scheduler":scheduler,"denoise":float(denoise),
           "model":["1",0],"positive":["4",0],"negative":["5",0],"latent_image":["6",0]}},
      "8":{"class_type":"VAEDecode","inputs":{"samples":["7",0],"vae":["3",0]}},
      "9":{"class_type":"SaveImage","inputs":{"images":["8",0],"filename_prefix":"mungbeans_FLUX3"}}
    }
    refs=[]
    if main_name: refs.append(main_name)
    if use_reference:
        if not ref_name: raise gr.Error("Secondary reference is enabled but no image is supplied.")
        refs.append(ref_name)
    if refs:
        if not node_available("ReferenceMultiLatent"):
            raise gr.Error("FLUX 3 image edit requires ReferenceMultiLatent custom node.")
        p["10"]={"class_type":"ConditioningZeroOut","inputs":{"conditioning":["4",0]}}
        inputs={"resolution":"resize","resolution.megapixels":float(scale_megapixels),
                "positive":["4",0],"negative":["10",0],"vae":["3",0]}
        for i,filename in enumerate(refs):
            nid=str(11+i)
            p[nid]={"class_type":"LoadImage","inputs":{"image":filename}}
            inputs[f"images.image{i}"]=[nid,0]
        p["17"]={"class_type":"ReferenceMultiLatent","inputs":inputs}
        p["7"]["inputs"].update({"positive":["17",0],"negative":["17",1],"latent_image":["17",2]})
    else:
        p["6"]={"class_type":"EmptyFlux2LatentImage","inputs":{"width":int(width),"height":int(height),"batch_size":1}}
    return p, f"FLUX 3 + {choice_rel(clip)} + {choice_rel(vae)}"

def build_krea_prompt(model_value: str, prompt_text: str, negative_text: str, width: int, height: int, steps: int, cfg: float, seed: int, sampler: str, scheduler: str, main_name=None, denoise=1.0):
    model = choice_rel(model_value)
    clip = choose_choice(SCANS["clips"], ["qwen3vl_4b", "qwen3vl"])
    vae = choose_choice(SCANS["vaes"], ["qwen_image_vae"])
    if not clip or not vae:
        raise gr.Error("Krea requires qwen3vl_4b text encoder and qwen_image_vae.")
    model_node, _, model_loader = load_diffusion_model(model_value)
    p = {
        "1": model_node,
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": choice_rel(clip), "type": "krea2", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_text or "", "clip": ["2", 0]}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": int(width), "height": int(height), "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(steps), "cfg": float(cfg), "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0, "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": choice_rel(vae)}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["7", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "KreaMung"}},
    }
    if main_name:
        # SNOFS Krea2 Edit is trained on full-noise target + two image-grounding paths.
        # A conventional VAE img2img latent alone does NOT implement this edit model.
        for required in ("CCTechKrea2IdentityEditSourcePatch", "CCTechKrea2IdentityEditGroundedEncode"):
            if not node_available(required):
                raise gr.Error(f"Krea 2 Edit requires {required}. Install/enable the Krea2 Edit nodes in ComfyUI.")
        p["10"] = {"class_type": "LoadImage", "inputs": {"image": main_name}}
        p["11"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["7", 0]}}
        p["12"] = {"class_type": "CCTechKrea2IdentityEditSourcePatch", "inputs": {"model": ["1", 0], "source_latent": ["11", 0], "vae": ["7", 0], "source_image": ["10", 0], "target_latent": ["5", 0], "fit_mode": "fit", "ref_boost": 1.0}}
        p["13"] = {"class_type": "CCTechKrea2IdentityEditGroundedEncode", "inputs": {"clip": ["2", 0], "prompt": prompt_text, "image": ["10", 0], "grounding_px": 768}}
        p["14"] = {"class_type": "CCTechKrea2IdentityEditGroundedEncode", "inputs": {"clip": ["2", 0], "prompt": negative_text or "", "image": ["10", 0], "grounding_px": 768}}
        p["6"]["inputs"].update({"model": ["12", 0], "positive": ["13", 0], "negative": ["14", 0], "denoise": 1.0})
    return p, f"Krea2 {'img2img' if main_name else 'generate'} {model_loader} + {choice_rel(clip)} + {choice_rel(vae)}"


def build_moss_prompt(model_value, clip_value, vae_value, prompt_text, negative_text,
                      main_name, ref_name, use_reference, width, height, steps, cfg,
                      seed, denoise, sampler, scheduler):
    """Build the MOSS Base graph from the Library txt2img/img2img workflows."""
    if use_reference:
        raise gr.Error("The MOSS Base workflow supports one source image. Turn off the second reference image.")
    info_nodes = ("SkipLayerGuidanceDiTSimple", "EmptyFlux2LatentImage", "VAEEncode", "VAEDecode")
    for node in info_nodes:
        if not node_available(node):
            raise gr.Error(f"MOSS Base requires the ComfyUI node {node}.")

    model_rel = choice_rel(model_value)
    clip_rel = choice_rel(clip_value)
    vae_rel = choice_rel(vae_value)
    if "moss" not in model_rel.casefold():
        raise gr.Error("Select a MOSS model file.")
    if not clip_value or not ("qwen3.5" in clip_rel.casefold() or "qwen3_5" in clip_rel.casefold()):
        raise gr.Error("MOSS requires its Qwen 3.5 text encoder.")
    if not vae_value or "flux2-vae" not in vae_rel.casefold():
        raise gr.Error("MOSS Base requires flux2-vae.safetensors.")

    prompt = {}
    model_cat = choice_category(model_value)
    if model_rel.casefold().endswith(".gguf") and node_available("UnetLoaderGGUFDynamicVRAM"):
        model_node = {"class_type":"UnetLoaderGGUFDynamicVRAM",
                      "inputs":filtered_inputs("UnetLoaderGGUFDynamicVRAM", {"unet_name":model_rel})}
        model_ref, model_loader = ["1",0], "UnetLoaderGGUFDynamicVRAM"
    else:
        if model_cat == "checkpoints" and not model_rel.casefold().endswith(".gguf"):
            raise gr.Error("MOSS safetensors are separate diffusion weights. Put them in models/diffusion_models or models/unet.")
        model_node, model_ref, model_loader = load_diffusion_model(model_value)
    prompt["1"] = model_node

    if clip_rel.casefold().endswith(".gguf"):
        if node_available("CLIPLoaderGGUFDynamicVRAM"):
            clip_node = {"class_type":"CLIPLoaderGGUFDynamicVRAM",
                         "inputs":filtered_inputs("CLIPLoaderGGUFDynamicVRAM",
                             {"clip_name":clip_rel,"type":"moss_image","device":"default"})}
            clip_loader = "CLIPLoaderGGUFDynamicVRAM"
        elif node_available("CLIPLoaderGGUF"):
            clip_node = {"class_type":"CLIPLoaderGGUF",
                         "inputs":filtered_inputs("CLIPLoaderGGUF",
                             {"clip_name":clip_rel,"type":"moss_image","device":"default"})}
            clip_loader = "CLIPLoaderGGUF"
        else:
            raise gr.Error("MOSS GGUF encoder needs ComfyUI-GGUF (CLIPLoaderGGUF).")
    else:
        clip_node = {"class_type":"CLIPLoader",
                     "inputs":filtered_inputs("CLIPLoader",
                         {"clip_name":clip_rel,"type":"moss_image","device":"default"})}
        clip_loader = "CLIPLoader (moss_image)"
    prompt["2"] = clip_node
    prompt["3"] = {"class_type":"VAELoader","inputs":{"vae_name":vae_rel}}
    prompt["4"] = {"class_type":"CLIPTextEncode","inputs":{"clip":["2",0],"text":prompt_text}}
    prompt["5"] = {"class_type":"CLIPTextEncode","inputs":{"clip":["2",0],"text":negative_text or ""}}
    prompt["6"] = {"class_type":"SkipLayerGuidanceDiTSimple","inputs":{
        "model":model_ref,"double_layers":"",
        "single_layers":"" if "turbo" in model_rel.casefold() else "22",
        "start_percent":0.0,"end_percent":1.0}}
    if main_name:
        prompt["7"] = {"class_type":"LoadImage","inputs":{"image":main_name}}
        prompt["8"] = {"class_type":"VAEEncode","inputs":{"pixels":["7",0],"vae":["3",0]}}
        latent_ref = ["8",0]
    else:
        prompt["9"] = {"class_type":"EmptyFlux2LatentImage","inputs":{
            "width":int(width),"height":int(height),"batch_size":1}}
        latent_ref = ["9",0]
    prompt["10"] = {"class_type":"KSampler","inputs":{
        "seed":int(seed),"steps":int(steps),"cfg":float(cfg),"sampler_name":sampler,
        "scheduler":scheduler,"denoise":float(denoise),"model":["6",0],
        "positive":["4",0],"negative":["5",0],"latent_image":latent_ref}}
    prompt["11"] = {"class_type":"VAEDecode","inputs":{"samples":["10",0],"vae":["3",0]}}
    prompt["12"] = {"class_type":"SaveImage","inputs":{"images":["11",0],"filename_prefix":"MUNGON_MOSS"}}
    return prompt, f"MOSS Base {model_loader} + {clip_loader} (moss_image) + {vae_rel}"


def build_wan_aio_frame_prompt(model_value, prompt_text, negative_text, main_name,
                                width, height, seed, steps=4, cfg=1.0,
                                sampler="dpmpp_sde", scheduler="beta"):
    """Build a single-frame still workflow from the WAN 2.2 Rapid Mega AIO checkpoint."""
    model_rel = choice_rel(model_value)
    if not model_rel.casefold().endswith(".safetensors") or "wan2.2-rapid-mega-aio" not in model_rel.casefold():
        raise gr.Error("Select the WAN 2.2 Rapid Mega AIO safetensors checkpoint.")
    required = ("CheckpointLoaderSimple", "CLIPTextEncode", "WanImageToVideo",
                "WanVaceToVideo", "ModelSamplingSD3", "KSampler", "VAEDecode", "SaveImage")
    for node in required:
        if not node_available(node):
            raise gr.Error(f"WAN 2.2 Rapid AIO requires {node} in ComfyUI.")
    out_w = max(256, (int(width) // 16) * 16)
    out_h = max(256, (int(height) // 16) * 16)
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model_rel}},
        "2": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": prompt_text}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": negative_text or ""}},
    }
    if main_name:
        graph["5"] = {"class_type": "LoadImage", "inputs": {"image": main_name}}
        graph["6"] = {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "vae": ["1", 2],
            "width": out_w, "height": out_h, "length": 1, "batch_size": 1,
            "start_image": ["5", 0],
        }}
        loader_desc = "WAN 2.2 Rapid AIO / one-frame image edit / WanImageToVideo"
    else:
        graph["6"] = {"class_type": "WanVaceToVideo", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "vae": ["1", 2],
            "width": out_w, "height": out_h, "length": 1, "batch_size": 1,
            "strength": 0.0,
        }}
        loader_desc = "WAN 2.2 Rapid AIO / one-frame text generation / VACE strength 0"
    graph["7"] = {"class_type": "KSampler", "inputs": {
        "model": ["2", 0], "seed": int(seed), "steps": max(4, int(steps)),
        "cfg": float(cfg), "sampler_name": sampler, "scheduler": scheduler,
        "positive": ["6", 0], "negative": ["6", 1], "latent_image": ["6", 2],
        "denoise": 1.0,
    }}
    graph["8"] = {"class_type": "VAEDecode", "inputs": {
        "samples": ["7", 0], "vae": ["1", 2],
    }}
    graph["9"] = {"class_type": "SaveImage", "inputs": {
        "images": ["8", 0], "filename_prefix": "MUNGON_WAN22_OneFrame",
    }}
    return graph, loader_desc


# Fixed Qwen Image 2.1 Turbo schedule from the published model and ComfyUI template.
QWEN21_TURBO_SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"

def build_qwen21_turbo_prompt(model_value, clip_value, vae_value, prompt_text, negative_text,
                              main_name, ref_name, use_reference, width, height, seed,
                              use_lora=False, lora_value=None, lora_strength=1.0,
                              use_lora2=False, lora2_value=None, lora2_strength=1.0,
                              use_lora3=False, lora3_value=None, lora3_strength=1.0):
    """Build native Qwen Image 2.1 Turbo graph for safetensors or GGUF weights."""
    model_rel = choice_rel(model_value)
    clip_rel = choice_rel(clip_value)
    vae_rel = choice_rel(vae_value)
    model_low = model_rel.casefold()
    clip_low = clip_rel.casefold()
    is_gguf = model_low.endswith(".gguf")
    is_aisha_qwen_turbo = "aisha" in model_low and "qwen" in model_low and "turbo" in model_low
    is_qwen_turbo = ("qwen-image-2.1-turbo" in model_low
                     or "qwen_image_2.1_turbo" in model_low
                     or is_aisha_qwen_turbo)
    if not is_qwen_turbo:
        raise gr.Error("Select a Qwen Image 2.1 Turbo model.")
    if "qwen_image_2.1_vae" not in vae_rel.casefold():
        raise gr.Error("Qwen Image 2.1 Turbo requires qwen_image_2.1_vae_bf16.safetensors.")
    if is_gguf:
        needed = ("TextEncodeQwenImage21", "ManualSigmas", "SamplerCustom", "KSamplerSelect",
                  "UnetLoaderGGUF", "CLIPLoaderGGUF", "EmptySD3LatentImage", "VAEDecode", "SaveImage")
        if "qwen" not in clip_low or not clip_low.endswith(".gguf"):
            raise gr.Error("Qwen Image 2.1 GGUF requires its matching Qwen3-VL GGUF text encoder.")
        model_loader = "UnetLoaderGGUF"
        clip_loader = "CLIPLoaderGGUF"
    else:
        needed = ("TextEncodeQwenImage21", "ManualSigmas", "SamplerCustom", "KSamplerSelect",
                  "UNETLoader", "CLIPLoader", "EmptySD3LatentImage", "VAEDecode", "SaveImage")
        if "qwen3vl_8b" not in clip_low or not clip_low.endswith(".safetensors"):
            raise gr.Error("Aisha/Qwen Image 2.1 Turbo requires the Qwen3-VL 8B safetensors encoder (for example qwen3vl_8b_w4a8.safetensors).")
        model_loader = "UNETLoader"
        clip_loader = "CLIPLoader"
    for node in needed:
        if not node_available(node):
            raise gr.Error(f"Qwen Image 2.1 Turbo requires {node} in ComfyUI.")

    graph = {
      "1": {"class_type": model_loader, "inputs": {"unet_name": model_rel}},
      "2": {"class_type": clip_loader, "inputs": {"clip_name": clip_rel, "type": "qwen_image"}},
      "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae_rel}},
      "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
          "clip": ["2", 0], "prompt": prompt_text, "negative_prompt": negative_text or "",
          "resolution": 1024, "vae": ["3", 0]}},
      "5": {"class_type": "EmptySD3LatentImage", "inputs": {
          "width": int(width), "height": int(height), "batch_size": 1}},
      "6": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
      "7": {"class_type": "ManualSigmas", "inputs": {"sigmas": QWEN21_TURBO_SIGMAS}},
      "8": {"class_type": "SamplerCustom", "inputs": {
          "model": ["1", 0], "add_noise": True, "noise_seed": int(seed), "cfg": 1.0,
          "positive": ["4", 0], "negative": ["4", 1], "sampler": ["6", 0],
          "sigmas": ["7", 0], "latent_image": ["5", 0]}},
      "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
      "10": {"class_type": "SaveImage", "inputs": {
          "images": ["9", 0], "filename_prefix": "MUNGON_AishaQwenTurbo"}},
    }
    # Qwen Image 2.1 img2img supplies the source to the Qwen encoder as an image condition.
    if main_name:
        graph["11"] = {"class_type": "LoadImage", "inputs": {"image": main_name}}
        graph["4"]["inputs"]["image_1"] = ["11", 0]
    if use_reference:
        if not ref_name:
            raise gr.Error("Reference Image is enabled but no image is uploaded.")
        graph["12"] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
        graph["4"]["inputs"]["image_2" if main_name else "image_1"] = ["12", 0]
    for enabled, value, strength, num in (
        (use_lora, lora_value, lora_strength, "91"),
        (use_lora2, lora2_value, lora2_strength, "92"),
        (use_lora3, lora3_value, lora3_strength, "93"),
    ):
        if enabled and value:
            graph[num] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": graph["8"]["inputs"]["model"],
                "lora_name": choice_rel(value),
                "strength_model": float(strength)}}
            graph["8"]["inputs"]["model"] = [num, 0]
    return graph, f"Qwen Image 2.1 Turbo / 8 fixed Euler sigma steps / Qwen3-VL 8B / {Path(vae_rel).name}"


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
    if main_name:
        p["4"] = {"class_type": "LoadImage", "inputs": {"image": main_name}}
    else:
        p["4"] = {"class_type": "EmptyImage", "inputs": {"width": int(width), "height": int(height), "batch_size": 1, "color": 0}}
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
    return p, f"{up_rel} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ exact {float(upscale_by):.2f}ÃƒÆ’Ã¢â‚¬â€ ({target_w}ÃƒÆ’Ã¢â‚¬â€{target_h})"


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

def wait_for_result(prompt_id: str, progress: gr.Progress, timeout_seconds: int = 600):
    global _cancel_requested
    start = time.time()
    while time.time() - start < timeout_seconds:
        if _cancel_requested:
            raise gr.Error("Generation cancelled.")
        time.sleep(1.0)
        try:
            hist = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
        except Exception:
            hist = {}
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
            status = item.get("status", {})
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                detail = "ComfyUI execution failed"
                for entry in messages:
                    if isinstance(entry, (list, tuple)) and entry and entry[0] == "execution_error":
                        detail = entry[1].get("exception_message", detail)
                        break
                raise gr.Error(detail)
        elapsed = int(time.time() - start)
        progress(min(0.95, 0.40 + elapsed / max(1, timeout_seconds) * 0.55), desc=f"Generating | {elapsed}s")
        yield f"Waiting for ComfyUI progress | {elapsed}s elapsed"
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
    live_console_begin(f"Preparing {mode} | {Path(choice_rel(model_value)).name if model_value else 'model'}")
    yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), live_console_text())
    if not comfy_alive(3):
        raise gr.Error(f"Cannot reach this pod's ComfyUI at {COMFY_URL}. Start this pod's configured ComfyUI backend.")
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
    if family == "MOSS" and (use_lora_manager or any((use_lora, use_lora2, use_lora3))):
        raise gr.Error("The Library MOSS Base workflows do not include LoRA support; disable the LoRA controls for this run.")
    validate_lora_stack(model_value, family, [
        (use_lora, lora_value), (use_lora2, lora2_value), (use_lora3, lora3_value)
    ])
    if use_lora_manager and any((use_lora, use_lora2, use_lora3)):
        raise gr.Error("Choose either LoraManager unlimited stack or the standard 3-slot stack, not both.")
    if use_controlnet and eff_mode in ("MOSS - Image Generate", "MOSS - Image Edit", "Qwen Rapid - Image Edit", "Ultimate SD Upscale", "Standard Model Upscale"):
        raise gr.Error(f"OpenPose ControlNet is not connected in {eff_mode}. Turn it off or choose a compatible FLUX/checkpoint mode.")

    # Source resolution is meaningful only for image-driven modes.
    source_capable = eff_mode in ("MOSS - Image Edit", "Qwen Image 2.1 Turbo - Image Edit", "FLUX 3 - Image Edit", "FLUX.2 Klein - Image Edit", "Qwen Rapid - Image Edit", "Krea - Image Edit", "Checkpoint - Img2Img")
    out_w, out_h, size_mode = resolve_size(main, bool(use_source and source_capable), preserve_aspect, width, height)

    if seed is None or int(seed) < 0:
        real_seed = random.randint(0, 2**63 - 1)
    else:
        real_seed = int(seed)

    live_console_set_status("Uploading source and reference images")
    yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), live_console_text())
    progress(0.05, desc="Uploading imagesÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦")
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

    live_console_set_status(f"Building {eff_mode} pipeline")
    yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), live_console_text())
    progress(0.15, desc=f"Building {eff_mode} pipelineÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦")
    if eff_mode in ("FLUX 3 - Image Edit", "FLUX 3 - Image Generate"):
        if eff_mode.endswith("Image Edit") and not main_name:
            raise gr.Error("FLUX 3 Image Edit requires a Main Image.")
        api_prompt, loader_desc = build_flux3_prompt(
            model_value, prompt_text, negative_text, actual_clip, vae_value,
            main_name if eff_mode.endswith("Image Edit") else None,
            ref_name, bool(use_reference and eff_mode.endswith("Image Edit")),
            steps, cfg, real_seed, denoise, out_w, out_h, sampler, scheduler, scale_megapixels)
    elif eff_mode == "FLUX.2 Klein - Image Edit":
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
    elif eff_mode in ("Qwen Image 2.1 Turbo - Image Generate", "Qwen Image 2.1 Turbo - Image Edit"):
        api_prompt, loader_desc = build_qwen21_turbo_prompt(
            model_value, actual_clip, vae_value, prompt_text, negative_text,
            main_name, ref_name, use_reference, out_w, out_h, real_seed,
            use_lora, lora_value, lora_strength, use_lora2, lora2_value, lora2_strength,
            use_lora3, lora3_value, lora3_strength)
    elif eff_mode in ("WAN 2.2 Rapid AIO - Text to Image", "WAN 2.2 Rapid AIO - Image Edit"):
        if eff_mode.endswith("Image Edit") and not main_name:
            raise gr.Error("WAN 2.2 Rapid AIO image edit requires a Main Image.")
        api_prompt, loader_desc = build_wan_aio_frame_prompt(
            model_value, prompt_text, negative_text,
            main_name if eff_mode.endswith("Image Edit") else None,
            out_w, out_h, real_seed, steps, cfg, sampler, scheduler)
    elif eff_mode == "Qwen Rapid - Image Edit":
        if not main_name:
            raise gr.Error("Qwen Rapid edit requires a Main Image.")
        api_prompt, loader_desc = build_qwen_prompt(
            model_value, actual_clip, vae_value, prompt_text, negative_text, main_name, ref_name, use_reference,
            steps, cfg, real_seed, denoise, out_w, out_h, sampler, scheduler,
            use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
        )
    elif eff_mode == "Qwen Rapid - Image Generate":
        api_prompt, loader_desc = build_qwen_prompt(
            model_value, actual_clip, vae_value, prompt_text, negative_text, None, None, False,
            steps, cfg, real_seed, 1.0, out_w, out_h, sampler, scheduler,
            use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
        )
    elif eff_mode in ("MOSS - Image Generate", "MOSS - Image Edit"):
        if eff_mode == "MOSS - Image Edit" and not main_name:
            raise gr.Error("MOSS img2img requires a Main Image.")
        api_prompt, loader_desc = build_moss_prompt(
            model_value, actual_clip, vae_value, prompt_text, negative_text,
            main_name if eff_mode == "MOSS - Image Edit" else None,
            ref_name, bool(use_reference), out_w, out_h, steps, cfg, real_seed,
            denoise if eff_mode == "MOSS - Image Edit" else 1.0, sampler, scheduler)
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
    elif eff_mode in ("Krea - Image Edit", "Krea - Image Generate"):
        if eff_mode == "Krea - Image Edit" and not main_name:
            raise gr.Error("Krea Image Edit requires a Main Image.")
        api_prompt, loader_desc = build_krea_prompt(
            model_value, prompt_text, negative_text, out_w, out_h, steps, cfg,
            real_seed, sampler, scheduler,
            main_name=main_name if eff_mode == "Krea - Image Edit" else None,
            denoise=denoise if eff_mode == "Krea - Image Edit" else 1.0,
        )
    elif eff_mode == "Checkpoint - Generate":
        api_prompt, loader_desc = build_checkpoint_prompt(
            model_value, prompt_text, negative_text, None, True,
            steps, cfg, real_seed, 1.0, out_w, out_h, sampler, scheduler,
            use_lora, lora_value, lora_strength,
            use_lora2, lora2_value, lora2_strength, use_lora3, lora3_value, lora3_strength,
            pose_name, use_controlnet, controlnet_value, controlnet_strength, controlnet_start, controlnet_end,
        )

    live_console_set_status(f"Pipeline ready | {loader_desc}")
    yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), live_console_text())
    progress(0.30, desc="Queueing in ComfyUI")
    client_id = uuid.uuid4().hex
    ws_stop = threading.Event()
    ws_ready = threading.Event()
    node_map = {str(node_id): node.get("class_type", "ComfyUI node") for node_id, node in api_prompt.items()}
    listener = threading.Thread(
        target=_comfy_progress_listener,
        args=(client_id, "", node_map, ws_stop, ws_ready),
        daemon=True,
        name="MUNGON-ComfyUI-progress",
    )
    listener.start()
    ws_ready.wait(2.0)
    try:
        r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": api_prompt, "client_id": client_id}, timeout=30)
        if not r.ok:
            live_console_log("ComfyUI rejected the workflow: " + r.text[:300])
            raise gr.Error(f"ComfyUI rejected the workflow:\n{r.text}")
        _current_prompt_id = r.json().get("prompt_id")
        if not _current_prompt_id:
            raise gr.Error("ComfyUI did not return a prompt_id.")
        live_console_log(f"Queued | Prompt {_current_prompt_id[:8]}")
        result_stream = wait_for_result(_current_prompt_id, progress)
        while True:
            try:
                status_line = next(result_stream)
            except StopIteration as completed:
                result, _hist = completed.value
                break
            live_console_set_status(status_line)
            yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), live_console_text())
        live_console_finish(f"Completed | {result.width} x {result.height}")
    finally:
        ws_stop.set()
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
        f"Mode: {eff_mode} | Family: {family} | Seed: {real_seed} | Output: {result.width}ÃƒÆ’Ã¢â‚¬â€{result.height} "
        f"| Requested: {out_w}ÃƒÆ’Ã¢â‚¬â€{out_h} ({size_mode}) | Loader: {loader_desc}"
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
    yield result, info, gr.update(choices=list(_prompt_history), value=prompt_text.strip() if prompt_text.strip() else None), gr.update(value=real_seed) if seed_lock else gr.update(), live_console_text()


def cancel_generation():
    global _cancel_requested
    _cancel_requested = True
    try:
        r = requests.post(f"{COMFY_URL}/interrupt", timeout=5)
        message = "Interrupt sent to ComfyUI." if r.ok else f"Interrupt returned HTTP {r.status_code}."
    except Exception as e:
        message = f"Could not interrupt ComfyUI: {e}"
    live_console_log(message)
    return message, live_console_text()


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
    if "--port" not in args and not any(a.startswith("--port=") for a in args):
        from urllib.parse import urlsplit
        args += ["--port", str(urlsplit(COMFY_URL).port or 8191)]
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
        env = os.environ.copy()
        if "omnixpu" in str(main).casefold():
            env.update({"OMNI_ATTN_BACKEND": "torch", "OMNIXPU_ENABLE": "1", "COMFY_SAFETENSORS_PREAD": "1"})
        _owned_comfy_process = subprocess.Popen(
            cmd,
            cwd=str(main.parent),
            env=env,
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
        _comfy_log.append("Stopping GUI-owned ComfyUI processÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦")
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
        return "Check this pod's COMFY_URL and ComfyUI service."
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
        return "This pod's ComfyUI is not connected; check COMFY_URL and refresh models."
    if comfy_alive(1):
        owned = _owned_comfy_process is not None and _owned_comfy_process.poll() is None
        return f"ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¢ ComfyUI ONLINE ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {COMFY_URL}" + (f" ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â GUI-owned PID {_owned_comfy_process.pid}" if owned else " ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â external process")
    return f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â´ ComfyUI OFFLINE ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {COMFY_URL}"


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
        return f"RunPod output folder: {p} (on this pod volume)."
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
        f"Scanned ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Models: {len(scans['models'])} | Encoders: {len(scans['clips'])} | VAEs: {len(scans['vaes'])} | LoRAs: {len(scans['loras'])} | Upscalers: {len(scans['upscalers'])}",
    )


def on_model_change(model_value, family_override, mode, show_all_loras, text_preset, current_clip, main_image=None):
    """When the user picks a model, auto-fill family, text encoder, VAE, and LoRA lists."""
    scans = current_scans()
    family = detect_family(model_value, family_override)
    eff = effective_mode(mode, family, pilify(main_image) is not None)
    rec = recommendations(model_value, family, eff)
    loras = compatible_lora_choices(scans["loras"], family, show_all_loras)

    # Text encoder
    clip = current_clip
    if family == "FLUX.2 Klein":
        clip = choose_text_encoder(scans["clips"], text_preset, current_clip, model_value)
    elif family == "FLUX 3":
        clip = choose_choice(scans["clips"], ["qwen3vl_4b_fp8_scaled", "qwen3vl_4b_int8", "qwen3vl_4b"])
    elif family == "Qwen Image 2.1 Turbo":
        model_low = choice_rel(model_value).casefold() if model_value else ""
        if model_low.endswith(".gguf"):
            clip = choose_choice(scans["clips"], ["Qwen-Image-2.1-Turbo-Uncensored-AD-Q6_K.gguf"])
        else:
            clip = choose_choice(scans["clips"], ["qwen3vl_8b_w4a8", "qwen3vl_8b_int8_convrot", "qwen3vl_8b_bf16"])
    elif family == "Qwen Rapid":
        clip = choose_choice(scans["clips"], [
            "Qwen2.5-VL-7B-Instruct-Q4_K_M", "Qwen2.5-VL-7B", "qwen2.5-vl",
            "qwen_image", "qwen",
        ])
    elif family == "MOSS":
        clip = choose_text_encoder(scans["clips"], text_preset, current_clip, model_value)

    # VAE
    vae = choose_choice(scans["vaes"], ["flux2-vae"]) if family == "FLUX 3" else choose_vae_for_model(scans["vaes"], model_value, family)

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
        rec["steps"], rec["cfg"], rec["sampler"], rec["scheduler"], rec["denoise"],
    )


def on_main_image_change(model_value, family_override, mode, main_image):
    family = detect_family(model_value, family_override)
    eff = effective_mode(mode, family, pilify(main_image) is not None)
    rec = recommendations(model_value, family, eff)
    return rec["text"], rec["steps"], rec["cfg"], rec["sampler"], rec["scheduler"], rec["denoise"]


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
    is_generate = mode in ("FLUX 3 - Image Generate", "FLUX.2 Klein - Image Generate", "Checkpoint - Generate")
    is_upscale = mode in ("Ultimate SD Upscale", "Standard Model Upscale")
    is_standard_upscale = mode == "Standard Model Upscale"
    image_needed = mode in ("FLUX 3 - Image Edit", "FLUX.2 Klein - Image Edit", "Qwen Rapid - Image Edit", "Checkpoint - Img2Img", "Ultimate SD Upscale", "Standard Model Upscale", "Auto")
    reference_supported = mode in ("FLUX 3 - Image Edit", "FLUX.2 Klein - Image Edit", "Qwen Rapid - Image Edit", "Auto")
    return (
        gr.update(visible=image_needed),
        gr.update(visible=reference_supported),
        gr.update(visible=not is_standard_upscale),
        gr.update(value=False if is_generate or is_upscale else True, interactive=not is_generate and not is_upscale),
        gr.update(visible=is_upscale),
        gr.update(visible=not is_standard_upscale),
        gr.update(visible=not is_standard_upscale),
        gr.update(visible=not is_standard_upscale),
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
# Prefer 9B Klein ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ big Aisha ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Phr00t/Qwen Rapid ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ anything Klein ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ fallback
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

with gr.Blocks(title="MUNGPOD | RunPod ComfyUI") as demo:

    with gr.Row(equal_height=True, elem_id="one-row-toolbar", elem_classes=["compact-model-bar"]):
        model_dd = gr.Dropdown(choices=SCANS["models"], value=DEFAULT_MODEL, label="Model", scale=4, min_width=220, container=False)
        manual_models = gr.Checkbox(False, label="Manual", scale=0, min_width=108, container=False, elem_id="manual-toggle")
        generate_top = gr.Button("Generate", variant="primary", size="sm", scale=1)
        stop_top = gr.Button("Stop", variant="stop", size="sm", scale=1)
        status_toggle = gr.Button("Status", size="sm", scale=1)
        queue_status = gr.Textbox(value="Queue: checking...", label="", interactive=False, container=False, scale=2, min_width=160, elem_id="queue-status")

    queue_timer = gr.Timer(value=3.0)
    with gr.Group(visible=False) as status_panel:
        with gr.Row():
            comfy_status = gr.Textbox(value=status_text(), label="ComfyUI Status", interactive=False, scale=3)
            refresh_status_btn = gr.Button("Refresh Status", scale=1)
            cancel_btn = gr.Button("Stop / Interrupt", variant="stop", scale=1)

    with gr.Tabs(elem_id="main-tabs"):
        with gr.Tab("Generate / Edit"):
            with gr.Row():
                with gr.Column(scale=1, elem_classes=["mungon-resize"]):
                    mode = gr.Dropdown(
                        MODES, value=SETTINGS.get("last_mode", "Auto"), label="Mode",
                        info="Auto uses the selected model and Main Image to choose text-to-image or img2img. Choose Standard Model Upscale for the simple upscaler.",
                    )
                    with gr.Accordion("Manual settings - loaders and sampling", open=True, visible=False) as manual_models_group:
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
                            cfg = gr.Slider(0.5, 12.0, value=1.1, step=0.1, label="CFG")
                        with gr.Row():
                            sampler = gr.Dropdown(SAMPLERS, value="euler", label="Sampler")
                            scheduler = gr.Dropdown(SCHEDULERS, value="normal", label="Scheduler")
                        with gr.Row():
                            seed = gr.Number(value=-1, precision=0, label="Seed (-1 = random)")
                            seed_lock = gr.Checkbox(False, label="Lock seed after generation")
                            denoise = gr.Slider(0.05, 1.0, value=1.0, step=0.05, label="Denoise / Strength")

                        gr.Markdown("### Advanced Reference Scaling")
                        scale_method = gr.Dropdown(SCALE_METHODS, value="lanczos", label="Scaling Method")
                        scale_megapixels = gr.Slider(0.25, 4.0, value=2.0, step=0.25, label="Reference Megapixels")
                        resolution_steps = gr.Slider(1, 64, value=1, step=1, label="Resolution Steps")
                        gr.Markdown("Lanczos is the default for photographic references. Resolution Steps affects resize granularity, not diffusion quality.")


                    main_group = gr.Group(visible=True)
                    with main_group:
                        with gr.Row(equal_height=True):
                            with gr.Column(scale=1, min_width=180):
                                main_img = gr.Image(label="Main Image", type="pil", height=240)
                            with gr.Column(scale=1, min_width=180):
                                reference_group = gr.Group(visible=True)
                                with reference_group:
                                    reference_img = gr.Image(label="Reference Image (optional)", type="pil", height=240)
                                    use_reference = gr.Checkbox(False, label="Use Reference Image")

                    # Pose / OpenPose / ControlNet UI intentionally removed from the MUNGON build.
                    # Hidden compatibility values keep the existing generation pipeline stable without exposing pose controls.
                    pose_img = gr.State(None)
                    use_controlnet = gr.State(False)
                    controlnet_dd = gr.Dropdown(choices=[], value=None, visible=False)
                    controlnet_strength = gr.State(0.85)
                    controlnet_start = gr.State(0.0)
                    controlnet_end = gr.State(1.0)

                    prompt = gr.Textbox(label="Prompt", lines=5, placeholder="Describe what to generate or change...")
                    with gr.Row(equal_height=True, elem_id="mung-prompt-tools"):
                        prompt_history = gr.Dropdown(choices=list(_prompt_history), label="Last 5 Prompts", value=None, scale=3, min_width=140)
                        negative_prompt = gr.Dropdown(
                            choices=["", "blurry, low quality, artifacts, watermark, text", "bad anatomy, extra limbs, distorted proportions", "oversaturated, blurry, duplicate, out of frame"],
                            value="", label="Negative Prompt", allow_custom_value=True, interactive=True, scale=4, min_width=180,
                        )
                        steps = gr.Number(value=recommendations(DEFAULT_MODEL, DEFAULT_FAMILY, effective_mode("Auto", DEFAULT_FAMILY, False))["steps"], minimum=1, maximum=50, precision=0, label="Steps", scale=1, min_width=85)
                    upscale_group = gr.Group(visible=False)
                    with upscale_group:
                        gr.Markdown("### Upscale")
                        gr.Markdown("No prompt or diffusion steps needed. Choose the source image, upscaler, and final scale.")
                        upscale_dd = gr.Dropdown(choices=SCANS["upscalers"], value=DEFAULT_UPSCALE, label="Upscale Model")
                        upscale_by = gr.Slider(1.0, 4.0, value=2.0, step=0.25, label="Upscale By")

                    with gr.Row():
                        refresh_models_btn = gr.Button("Refresh Models")
                        run_btn = gr.Button("Generate", variant="primary", size="lg")

                    live_console = gr.Textbox(
                        value="Ready. Waiting for Generate.",
                        label="ComfyUI Live Console",
                        lines=7,
                        max_lines=9,
                        interactive=False,
                        elem_id="live-console",
                    )

                with gr.Column(scale=1, elem_classes=["mungon-resize"]):
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
                    use_source = gr.Checkbox(False, label="Use Source Image Resolution")
                    preserve_aspect = gr.Checkbox(False, label="Preserve Source Aspect Ratio when using manual resolution")
                    with gr.Group(visible=False) as manual_res_group:
                        res_preset = gr.Dropdown(list(RES_PRESETS.keys()), value="1024 ÃƒÆ’Ã¢â‚¬â€ 1024", label="Preset")
                        with gr.Row():
                            width = gr.Number(value=1024, precision=0, minimum=16, label="Width")
                            height = gr.Number(value=1024, precision=0, minimum=16, label="Height")




                    with gr.Group(visible=False):
                        recommendation_box = gr.Textbox(
                            value=recommendations(DEFAULT_MODEL, DEFAULT_FAMILY, effective_mode("Auto", DEFAULT_FAMILY, False))["text"],
                            interactive=False, lines=8, label="Internal Model Recommendations"
                        )
                        apply_rec_btn = gr.Button("Apply Recommended Settings")
                        my_note = gr.Textbox(label="My Notes for This Model", lines=5)
                        save_note_btn = gr.Button("Save Model Note")
                        note_status = gr.Textbox(label="Note Status", interactive=False)


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
            extra_args = gr.Textbox(value=SETTINGS.get("extra_args", ""), label="Extra Arguments", placeholder="Any extra ComfyUI flagsÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦")
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
    def toggle_panel(opened):
        opened = not opened
        return opened, gr.update(visible=opened)
    status_toggle.click(toggle_panel, inputs=status_open, outputs=[status_open, status_panel])
    manual_models.change(lambda checked: gr.update(visible=checked), inputs=manual_models, outputs=manual_models_group)
    refresh_status_btn.click(status_text, outputs=comfy_status)
    queue_timer.tick(queue_status_text, outputs=queue_status, show_progress="hidden")
    demo.load(queue_status_text, outputs=queue_status)
    demo.load(on_mode_change, inputs=mode, outputs=[main_group, reference_group, negative_prompt, use_source, upscale_group, prompt, prompt_history, steps])
    cancel_btn.click(cancel_generation, outputs=[info, live_console])

    use_lora.change(on_lora_toggle, inputs=use_lora, outputs=[lora_dd, lora_strength])
    use_lora2.change(on_lora_toggle, inputs=use_lora2, outputs=[lora2_dd, lora2_strength])
    use_lora3.change(on_lora_toggle, inputs=use_lora3, outputs=[lora3_dd, lora3_strength])
    text_encoder_preset.change(on_text_preset, inputs=[text_encoder_preset, clip_dd], outputs=clip_dd)
    mode.change(on_mode_change, inputs=mode, outputs=[main_group, reference_group, negative_prompt, use_source, upscale_group, prompt, prompt_history, steps])
    use_source.change(on_use_source, inputs=[use_source, main_img], outputs=[manual_res_group, width, height, res_preset])
    width.change(on_width_change, inputs=[width, preserve_aspect, main_img], outputs=height)
    preserve_aspect.change(on_width_change, inputs=[width, preserve_aspect, main_img], outputs=height)
    res_preset.change(apply_preset, inputs=res_preset, outputs=[width, height])
    prompt_history.change(use_prompt_history, inputs=prompt_history, outputs=prompt)

    model_dd.change(
        on_model_change,
        inputs=[model_dd, family_override, mode, show_all_loras, text_encoder_preset, clip_dd, main_img],
        outputs=[detected_family, recommendation_box, lora_dd, lora2_dd, lora3_dd, clip_dd, vae_dd, my_note, steps, cfg, sampler, scheduler, denoise],
    )
    family_override.change(
        on_model_change,
        inputs=[model_dd, family_override, mode, show_all_loras, text_encoder_preset, clip_dd, main_img],
        outputs=[detected_family, recommendation_box, lora_dd, lora2_dd, lora3_dd, clip_dd, vae_dd, my_note, steps, cfg, sampler, scheduler, denoise],
    )
    show_all_loras.change(
        on_model_change,
        inputs=[model_dd, family_override, mode, show_all_loras, text_encoder_preset, clip_dd, main_img],
        outputs=[detected_family, recommendation_box, lora_dd, lora2_dd, lora3_dd, clip_dd, vae_dd, my_note, steps, cfg, sampler, scheduler, denoise],
    )
    main_img.change(
        on_main_image_change,
        inputs=[model_dd, family_override, mode, main_img],
        outputs=[recommendation_box, steps, cfg, sampler, scheduler, denoise],
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
        outputs=[output_img, info, prompt_history, seed, live_console],
        show_progress="hidden",
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
    print("MUNGPOD RunPod GUI")
    print(f"Models: {len(SCANS['models'])} | Encoders: {len(SCANS['clips'])} | VAEs: {len(SCANS['vaes'])} | LoRAs: {len(SCANS['loras'])} | Upscalers: {len(SCANS['upscalers'])}")
    print(f"ComfyUI: {COMFY_URL}")
    gui_port = int(os.environ.get("MUNGPOD_PORT", "7866"))
    gui_host = os.environ.get("MUNGPOD_HOST", "0.0.0.0")
    print(f"RunPod GUI: http://{gui_host}:{gui_port}")
    print(f"ComfyUI root: {COMFY_ROOT} | discovered model roots: {len(MODEL_ROOTS)}")
    demo.queue().launch(
        server_name=gui_host,
        server_port=gui_port,
        inbrowser=False,
        theme=gr.themes.Soft(),
        css=(APP_DIR / "mungon.css").read_text(encoding="utf-8"),
    )
