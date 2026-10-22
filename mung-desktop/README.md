# MUNG desktop - latest recovered source

Published 22 October 2026 from `MUNG_DESKTOP_LATEST` in the F: recovery bundle.
The main source is `BEAVIS_FIXED.py`, last modified 13 October 2026. This was the
newest matching MUNG/BEAVIS application source found in the inspected Desktop,
Documents and F: locations. It is a recovered snapshot, not a newly rewritten app.

## Included

- Original `BEAVIS_FIXED.py`, both Windows launchers and all nine workflow templates.
- `source-manifest.json` records exact sizes and SHA256 hashes of the originals.
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

The app defaults to `http://127.0.0.1:8188`. Configure the appropriate ComfyUI/RunPod
URL in the app. Personal settings can be restored locally by copying your existing
`universal_comfy_gui_runpod_settings.json` beside the Python file. Do not commit
tokens, private URLs or saved prompts to this public repository.

## RunPod startup is separate

The sibling `runpod-startup` folder contains the current automatic model installer
and 8188 startup bundle. Uploading this desktop app does not automatically install
or run MUNG inside a pod. The desktop app connects to the ComfyUI backend.

## Checks

Python syntax and all JSON files were parsed successfully before publication.
Original application, launcher and workflow files were copied byte-for-byte and
checked against the source manifest. The GUI and GPU generations were not run as
part of this publication. Recovered templates can require additional custom nodes
or models beyond the minimal automatic startup model set.
