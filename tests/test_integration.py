import json
import os
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen


class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/system_stats", "/v1/models"):
            self.reply({"ok": True})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            plan = {"route": "klein_9b", "prompt": "enhanced test", "negative": "", "steps": 8, "cfg": 1.2, "denoise": 0.75, "reason": "test"}
            self.reply({"choices": [{"message": {"content": json.dumps(plan)}}]})
        elif self.path == "/prompt":
            self.reply({"prompt_id": "test-id"})
        else:
            self.send_error(404)


class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 18188), FakeHandler)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        env = os.environ | {
            "IMAGINE_HOST": "127.0.0.1",
            "IMAGINE_PORT": "17865",
            "COMFY_URL": "http://127.0.0.1:18188",
            "BRAIN_URL": "http://127.0.0.1:18188/v1",
        }
        cls.app = subprocess.Popen([sys.executable, "server.py"], env=env)
        for _ in range(30):
            try:
                urlopen("http://127.0.0.1:17865/api/status", timeout=1)
                break
            except Exception:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.app.terminate()
        cls.app.wait(timeout=5)
        cls.fake.shutdown()

    def get_json(self, path):
        with urlopen("http://127.0.0.1:17865" + path) as response:
            return json.load(response)

    def test_status_and_proxy(self):
        status = self.get_json("/api/status")
        self.assertTrue(status["comfy"])
        self.assertTrue(status["brain"])
        self.assertTrue(self.get_json("/comfy/system_stats")["ok"])

    def test_workflow_registry(self):
        registry = self.get_json("/api/workflows")
        routes = {item["route"]: item["configured"] for item in registry["routes"]}
        self.assertEqual(set(routes), {"klein_9b", "aisha_9b", "qwen_edit", "wan_fast", "wan_quality"})
        for route in ("klein_9b", "aisha_9b", "qwen_edit", "wan_fast", "wan_quality"):
            self.assertTrue(routes[route])

        wan = self.get_json("/api/workflow/wan_fast")
        classes = {node["class_type"] for node in wan["workflow"].values()}
        self.assertIn("SaveVideo", classes)

        quality = self.get_json("/api/workflow/wan_quality")
        qclasses = {node["class_type"] for node in quality["workflow"].values()}
        self.assertIn("SaveVideo", qclasses)
        self.assertNotIn("LoraLoaderModelOnly", qclasses)
        self.assertEqual(quality["workflow"]["81"]["inputs"]["steps"], 20)
        self.assertEqual(quality["workflow"]["81"]["inputs"]["end_at_step"], 10)
        self.assertEqual(quality["workflow"]["78"]["inputs"]["start_at_step"], 10)

    def test_brain_route(self):
        body = json.dumps({"prompt": "a portrait", "mode": "auto", "has_images": False}).encode()
        request = Request("http://127.0.0.1:17865/api/brain", data=body, headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            result = json.load(response)
        self.assertEqual(result["plan"]["route"], "klein_9b")
        self.assertEqual(result["plan"]["prompt"], "enhanced test")


if __name__ == "__main__":
    unittest.main()
