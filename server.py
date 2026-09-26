#!/usr/bin/env python3
"""MUNGBEAN Grok Imagine server: UI, ComfyUI proxy and multimodal director brain."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
WORKFLOW_DIR = ROOT / "config" / "workflows"
ROUTES = ("klein_9b", "aisha_9b", "qwen_edit", "wan_fast", "wan_quality")
HOST = os.getenv("IMAGINE_HOST", "0.0.0.0")
PORT = int(os.getenv("IMAGINE_PORT", "7865"))
COMFY = os.getenv("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
BRAIN = os.getenv("BRAIN_URL", "http://127.0.0.1:8090/v1").rstrip("/")
BRAIN_MODEL = os.getenv("BRAIN_MODEL", "").strip()
BRAIN_PREFERRED = os.getenv("BRAIN_PREFERRED", "mungbean-qwen3.5-27b").strip()
BRAIN_LAUNCHER = Path(os.getenv("BRAIN_LAUNCHER", str(ROOT / "START_BRAIN.sh")))
BRAIN_START_TIMEOUT = int(os.getenv("BRAIN_START_TIMEOUT", "180"))
MANAGE_BRAIN = os.getenv("MUNGBEAN_MANAGE_BRAIN", "0").lower() in {"1", "true", "yes", "on"}
RELEASE_BRAIN = os.getenv("MUNGBEAN_RELEASE_BRAIN", "1").lower() in {"1", "true", "yes", "on"}
MAX_REFERENCE_DATA_URL = int(os.getenv("BRAIN_MAX_REFERENCE_BYTES", str(14 * 1024 * 1024)))
_BRAIN_LOCK = threading.Lock()
_BRAIN_PROCESS = None

ROUTER_SYSTEM = """You are MUNGBEAN, the multimodal image/video director inside GENESIS.
Your job is to preserve the user's intent, improve execution quality, and choose the best runnable route.
Return exactly one JSON object and no markdown.

Routes:
qwen_edit = precise reference-image editing, identity/clothing/object transfer, or controlled edits.
klein_9b = high-quality image generation and flexible reference-driven generation.
aisha_9b = photorealistic adult-oriented image generation.
wan_fast = fast Wan 2.2 video generation.
wan_quality = higher-quality Wan 2.2 video generation.

The application may provide AVAILABLE ROUTES. Never select a route outside that list.
If the user manually selected a route, keep that route and improve the prompt for it.
When a reference image is supplied, inspect it and preserve requested identity/composition details.
Do not invent details the user did not ask for. Keep prompt wording concrete and visually useful.

Schema:
{"route":"...","prompt":"...","negative":"...","steps":8,"cfg":1.2,"denoise":0.75,
"reason":"short explanation","intent":"image_generation|image_edit|video_generation",
"reference_strategy":"none|preserve_identity|edit_reference|style_reference",
"postprocess":["identity","upscale","canvas"]}
Only include postprocess operations that materially help the request.
"""


def request_json(url: str, method: str = "GET", body=None, timeout: int = 30):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "application/json")
        return response.status, content_type, payload


def configured_routes() -> list[str]:
    return [route for route in ROUTES if (WORKFLOW_DIR / f"{route}.json").is_file()]


def brain_catalog() -> tuple[bool, list[str], str]:
    """Return brain reachability, exposed model ids, and selected model id."""
    try:
        _, _, raw = request_json(f"{BRAIN}/models", timeout=3)
        payload = json.loads(raw)
        models = []
        for item in payload.get("data", []):
            model_id = str(item.get("id", "")).strip()
            if model_id:
                models.append(model_id)
        if not models and isinstance(payload.get("models"), list):
            models = [str(x).strip() for x in payload["models"] if str(x).strip()]
        selected = BRAIN_MODEL or (models[0] if models else BRAIN_PREFERRED)
        return True, models, selected
    except Exception:
        return False, [], BRAIN_MODEL or BRAIN_PREFERRED


def free_comfy_memory() -> None:
    """Ask ComfyUI to release loaded models before a large brain takes the GPU."""
    try:
        request_json(
            f"{COMFY}/free",
            "POST",
            {"unload_models": True, "free_memory": True},
            timeout=15,
        )
    except Exception:
        pass


def ensure_brain() -> tuple[bool, list[str], str]:
    """Start the preferred brain on demand when RunPod-managed mode is enabled."""
    global _BRAIN_PROCESS
    online, models, selected = brain_catalog()
    if online or not MANAGE_BRAIN:
        return online, models, selected
    if not BRAIN_LAUNCHER.is_file():
        return False, [], BRAIN_PREFERRED

    with _BRAIN_LOCK:
        online, models, selected = brain_catalog()
        if online:
            return online, models, selected

        free_comfy_memory()
        log_path = Path(os.getenv("BRAIN_LOG", "/tmp/mungbean-brain.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("ab", buffering=0)
        try:
            _BRAIN_PROCESS = subprocess.Popen(
                [str(BRAIN_LAUNCHER)],
                cwd=str(ROOT),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()

        deadline = time.monotonic() + BRAIN_START_TIMEOUT
        while time.monotonic() < deadline:
            if _BRAIN_PROCESS.poll() is not None:
                return False, [], BRAIN_PREFERRED
            online, models, selected = brain_catalog()
            if online:
                return online, models, selected
            time.sleep(1)
        return False, [], BRAIN_PREFERRED


def release_managed_brain() -> None:
    """Release brain VRAM after planning so ComfyUI can own the single GPU."""
    global _BRAIN_PROCESS
    if not (MANAGE_BRAIN and RELEASE_BRAIN):
        return
    with _BRAIN_LOCK:
        proc = _BRAIN_PROCESS
        _BRAIN_PROCESS = None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def parse_plan_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    first, last = text.find("{"), text.rfind("}")
    if first >= 0 and last >= first:
        text = text[first:last + 1]
    return json.loads(text)


def safe_available_routes(value) -> list[str]:
    if value is None:
        return configured_routes()
    if not isinstance(value, list):
        return configured_routes()
    seen = []
    for route in value:
        route = str(route)
        if route in ROUTES and route not in seen and (WORKFLOW_DIR / f"{route}.json").is_file():
            seen.append(route)
    return seen


def fallback_route(prompt: str, has_images: bool, requested_mode: str, available: list[str]) -> str:
    if requested_mode in available:
        return requested_mode
    lower = prompt.lower()
    wants_video = bool(re.search(r"\b(video|animate|animation|motion|moving|clip)\b", lower))
    if wants_video:
        for route in ("wan_quality", "wan_fast"):
            if route in available:
                return route
    if has_images and "qwen_edit" in available:
        return "qwen_edit"
    for route in ("klein_9b", "aisha_9b", "qwen_edit", "wan_fast", "wan_quality"):
        if route in available:
            return route
    raise ValueError("No runnable MUNGBEAN routes are available.")


def normalize_plan(plan: dict, *, prompt: str, mode: str, has_images: bool, available: list[str]) -> dict:
    if not isinstance(plan, dict):
        plan = {}
    requested_route = mode if mode in ROUTES else ""
    route = requested_route or str(plan.get("route", ""))
    if route not in available:
        previous = route
        route = fallback_route(prompt, has_images, mode, available)
        reason = str(plan.get("reason", "")).strip()
        suffix = f"Selected {route} because {previous or 'the proposed route'} is not runnable on this backend."
        plan["reason"] = (reason + " · " + suffix).strip(" ·")
    plan["route"] = route
    plan["prompt"] = str(plan.get("prompt") or prompt).strip()
    plan["negative"] = str(plan.get("negative") or "")
    try:
        plan["steps"] = max(1, min(80, int(plan.get("steps", 8))))
    except (TypeError, ValueError):
        plan["steps"] = 8
    for key, default, low, high in (("cfg", 1.2, 0.0, 30.0), ("denoise", 0.75, 0.0, 1.0)):
        try:
            plan[key] = max(low, min(high, float(plan.get(key, default))))
        except (TypeError, ValueError):
            plan[key] = default
    if plan.get("intent") not in {"image_generation", "image_edit", "video_generation"}:
        plan["intent"] = "video_generation" if route.startswith("wan_") else ("image_edit" if has_images else "image_generation")
    if plan.get("reference_strategy") not in {"none", "preserve_identity", "edit_reference", "style_reference"}:
        plan["reference_strategy"] = "edit_reference" if has_images else "none"
    post = plan.get("postprocess", [])
    if not isinstance(post, list):
        post = []
    plan["postprocess"] = [str(x) for x in post if str(x) in {"identity", "upscale", "canvas"}]
    plan["reason"] = str(plan.get("reason") or "Prompt planned for the selected route.")
    return plan


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def send_bytes(self, status: int, content_type: str, payload: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status: int, value):
        self.send_bytes(status, "application/json; charset=utf-8", json.dumps(value).encode())

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def workflow_payload(self, route: str):
        if route not in ROUTES:
            return None
        path = WORKFLOW_DIR / f"{route}.json"
        if not path.is_file():
            return {"route": route, "configured": False}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            workflow = raw.get("prompt", raw)
            mapping = raw.get("_genesis_mapping", {})
            return {"route": route, "configured": True, "workflow": workflow, "mapping": mapping}
        except Exception as exc:
            return {"route": route, "configured": False, "error": str(exc)}

    def do_GET(self):
        if self.path == "/api/workflows":
            items = [self.workflow_payload(route) for route in ROUTES]
            return self.send_json(200, {"routes": [
                {k: v for k, v in item.items() if k not in {"workflow", "mapping"}}
                for item in items
            ]})
        if self.path.startswith("/api/workflow/"):
            route = self.path.split("/api/workflow/", 1)[1].split("?", 1)[0]
            item = self.workflow_payload(route)
            if item is None:
                return self.send_json(404, {"error": "Unknown route"})
            return self.send_json(200 if item.get("configured") else 404, item)
        if self.path == "/api/status":
            result = {
                "comfy": False,
                "brain": False,
                "brain_model": BRAIN_PREFERRED,
                "brain_models": [],
                "brain_managed": MANAGE_BRAIN,
                "brain_on_demand": False,
            }
            try:
                request_json(f"{COMFY}/system_stats", timeout=3)
                result["comfy"] = True
            except Exception:
                pass
            online, models, selected = brain_catalog()
            result.update(
                brain=online,
                brain_model=selected,
                brain_models=models,
                brain_on_demand=bool(MANAGE_BRAIN and not online),
            )
            return self.send_json(200, result)
        if self.path.startswith("/comfy/"):
            return self.proxy_comfy("GET")
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/brain":
            return self.brain_route()
        if self.path.startswith("/comfy/"):
            return self.proxy_comfy("POST")
        self.send_error(404)

    def brain_route(self):
        try:
            incoming = self.read_json()
            prompt = str(incoming.get("prompt", "")).strip()
            mode = str(incoming.get("mode", "auto"))
            has_images = bool(incoming.get("has_images"))
            available = safe_available_routes(incoming.get("available_routes"))
            if not prompt:
                return self.send_json(400, {"ok": False, "error": "A prompt is required for brain planning."})

            online, _, selected_model = ensure_brain()
            if not online:
                return self.send_json(
                    503,
                    {"ok": False, "error": "MUNGBEAN brain is unavailable. Check the 27B model pair and brain log."},
                )

            message = (
                f"Requested mode: {mode}\n"
                f"Reference image supplied: {has_images}\n"
                f"AVAILABLE ROUTES: {', '.join(available)}\n"
                f"User request: {prompt}"
            )
            reference = str(incoming.get("reference_data_url") or "")
            if reference and len(reference.encode("utf-8")) > MAX_REFERENCE_DATA_URL:
                return self.send_json(413, {"ok": False, "error": "Reference image is too large for brain planning."})
            if reference and not reference.startswith("data:image/"):
                reference = ""

            user_content = message
            if reference:
                user_content = [
                    {"type": "text", "text": message},
                    {"type": "image_url", "image_url": {"url": reference}},
                ]

            payload = {
                "model": selected_model,
                "temperature": 0.2,
                "max_tokens": 900,
                "messages": [
                    {"role": "system", "content": ROUTER_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
            }
            _, _, raw = request_json(f"{BRAIN}/chat/completions", "POST", payload, timeout=180)
            response = json.loads(raw)
            text = response["choices"][0]["message"]["content"]
            plan = normalize_plan(
                parse_plan_text(text),
                prompt=prompt,
                mode=mode,
                has_images=has_images,
                available=available,
            )
            return self.send_json(200, {"ok": True, "plan": plan, "brain_model": selected_model})
        except (HTTPError, URLError) as exc:
            return self.send_json(503, {"ok": False, "error": f"Brain server unavailable: {exc}"})
        except ValueError as exc:
            return self.send_json(409, {"ok": False, "error": str(exc)})
        except Exception as exc:
            return self.send_json(500, {"ok": False, "error": str(exc)})
        finally:
            release_managed_brain()

    def proxy_comfy(self, method: str):
        target = COMFY + self.path[len("/comfy"):]
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        req = Request(target, data=body, method=method)
        content_type = self.headers.get("Content-Type")
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            with urlopen(req, timeout=180) as response:
                return self.send_bytes(response.status, response.headers.get("Content-Type", "application/octet-stream"), response.read())
        except HTTPError as exc:
            return self.send_bytes(exc.code, exc.headers.get("Content-Type", "application/json"), exc.read())
        except Exception as exc:
            return self.send_json(502, {"error": str(exc)})


if __name__ == "__main__":
    print(f"MUNGBEAN Grok Imagine: http://{HOST}:{PORT}")
    print(f"ComfyUI backend: {COMFY}")
    print(f"Brain backend: {BRAIN}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
