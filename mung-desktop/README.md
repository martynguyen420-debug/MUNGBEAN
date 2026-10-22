# MUNG desktop - latest recovered source

Published 22 October 2026 from `MUNG_DESKTOP_LATEST` in the F: recovery bundle.
The main source is `BEAVIS_FIXED.py`, recovered from 13 October 2026 and fixed on 22 October 2026. This was the
newest matching MUNG/BEAVIS application source found in the inspected Desktop,
Documents and F: locations. This update fixes stale RunPod connection restoration.

## Included

- Updated `BEAVIS_FIXED.py`, both original Windows launchers and all nine workflow templates.
- `source-manifest.json` records the published sizes/hashes; `recovered-source-manifest.json` preserves the original snapshot record.
- A clean example settings file, with personal connection paths, saved prompt
  history and model notes omitted. Your original settings on F: are unchanged.

## Run on Windows

Download this repository using GitHub's **Code > Download ZIP**, extract it and open
the `mung-desktop` folder. The supplied `START_MUNG.bat` expects Python at:

```text
C:\ai\ComfyUI_windows_portable_b580\python_embeded\python.exe
```

If your portable ComfyUI is on F:, edit the BAT's `PY` path to the Python executable
in that installation. Run `START_MUNG.bat`. It launches the local MUNG interface;
ComfyUI or the RunPod backend must also be running.

The source declares `gradio`, `requests` and `pillow` as dependencies. Reuse the
existing working environment where possible. No dependency versions were recovered
as a lock file, so compatibility with a fresh package install has not been proven.

The app defaults to `http://127.0.0.1:8188`. In RunPod mode, each new MUNG session opens with an empty URL field. Paste the current
pod ComfyUI URL and click **Connect & Scan Pod Models**. It validates the URL before
switching the active connection or saving it. Failed attempts preserve the current
working connection. Old saved URLs never become active automatically. Personal settings can be restored locally by copying your existing
`universal_comfy_gui_runpod_settings.json` beside the Python file. Do not commit
tokens, private URLs or saved prompts to this public repository.

## RunPod startup is separate

The sibling `runpod-startup` folder contains the current automatic model installer
and 8188 startup bundle. Uploading this desktop app does not automatically install
or run MUNG inside a pod. The desktop app connects to the ComfyUI backend.

## Checks

Python syntax and all JSON files were parsed successfully before publication.
The connection fix passed six regression tests (including stale-URL suppression,
successful switching and failed-connection preservation). Published files are
checked against the updated source manifest. The GUI and GPU generations were not run as
part of this publication. Recovered templates can require additional custom nodes
or models beyond the minimal automatic startup model set.
