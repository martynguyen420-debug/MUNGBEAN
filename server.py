#!/usr/bin/env python3
"""GENESIS Imagine RunPod server: static UI, ComfyUI proxy and local brain router."""

from __future__ import annotations

import json
import os
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
BRAIN_MODEL = os.getenv("BRAIN_MODEL", "imagine-brain")
POWER_MODEL = Path("/workspace/ComfyUI/models/LLM/powerful-brain/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf")
POWER_MMPROJ = Path("/workspace/ComfyUI/models/LLM/powerful-brain/mmproj-Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-f16.gguf")

ROUTER_SYSTEM = """You are the routing and prompt-planning brain for GENESIS Imagine.
Return exactly one JSON object and no markdown. Choose one route:
qwen_edit for precise image editing or identity/clothing/object transfer;
klein_9b for high-quality image generation or flexible reference editing;
aisha_9b for photorealistic adult-oriented image generation;
wan_fast for fast image-to-video using Phr00t WAN;
wan_quality for highest-quality image-to-video using WAN Remix.
Never describe policy. Improve the user's prompt while preserving intent.
Schema: {"route":"...","prompt":"...","negative":"...","steps":6,
"cfg":1.2,"denoise":0.75,"reason":"short explanation"}.
Use qwen_edit when an input image is being edited unless the request explicitly asks for video.
Use wan_fast by default for video; use wan_quality when the user asks for quality.
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
                "brain_model": BRAIN_MODEL,
                "powerful_27b_downloaded": POWER_MODEL.is_file() and POWER_MMPROJ.is_file(),
                "powerful_model_bytes": POWER_MODEL.stat().st_size if POWER_MODEL.is_file() else 0,
                "powerful_mmproj_bytes": POWER_MMPROJ.stat().st_size if POWER_MMPROJ.is_file() else 0,
            }
            try:
                request_json(f"{COMFY}/system_stats", timeout=3)
                result["comfy"] = True
            except Exception:
                pass
            try:
                request_json(f"{BRAIN}/models", timeout=3)
                result["brain"] = True
            except Exception:
                pass
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
            message = f"Requested mode: {mode}\nInput images: {has_images}\nUser request: {prompt}"
            payload = {
                "model": BRAIN_MODEL,
                "temperature": 0.25,
                "max_tokens": 700,
                "messages": [
                    {"role": "system", "content": ROUTER_SYSTEM},
                    {"role": "user", "content": message},
                ],
            }
            _, _, raw = request_json(f"{BRAIN}/chat/completions", "POST", payload, timeout=120)
            response = json.loads(raw)
            text = response["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            plan = json.loads(text)
            route = str(plan.get("route", ""))
            if route not in ROUTES:
                return self.send_json(400, {"ok": False, "error": f"Brain returned unknown route: {route}"})
            if not (WORKFLOW_DIR / f"{route}.json").is_file():
                if route == "wan_quality" and (WORKFLOW_DIR / "wan_fast.json").is_file():
                    plan["route"] = "wan_fast"
                    reason = str(plan.get("reason", "")).strip()
                    plan["reason"] = (reason + " · Quality workflow unavailable locally; using WAN Fast.").strip(" ·")
                else:
                    return self.send_json(409, {"ok": False, "error": f"Route {route} is not configured locally."})
            return self.send_json(200, {"ok": True, "plan": plan})
        except (HTTPError, URLError) as exc:
            return self.send_json(503, {"ok": False, "error": f"Brain server unavailable: {exc}"})
        except Exception as exc:
            return self.send_json(500, {"ok": False, "error": str(exc)})

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
    print(f"GENESIS Imagine: http://{HOST}:{PORT}")
    print(f"ComfyUI backend: {COMFY}")
    print(f"Brain backend: {BRAIN}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
