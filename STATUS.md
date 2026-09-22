# Status — 2026-09-22

- Imagine UI integrated with a same-origin ComfyUI proxy.
- Local OpenAI-compatible brain endpoint integrated.
- Automatic image/video engine routing implemented.
- 27B-first, 9B-fallback brain launcher implemented.
- RunPod file/API verification command included.
- Static, shell, Python, proxy, and brain-route tests passing locally.

The 27B files cannot be truthfully marked as present until `./CHECK_BRAIN.sh` runs on the Pod. The application reports that result in `/api/status` and in the Brain card.
