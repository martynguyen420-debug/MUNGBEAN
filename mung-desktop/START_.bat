@echo off
setlocal
cd /d "%~dp0"
set "PY=C:\ai\ComfyUI_windows_portable_b580\python_embeded\python.exe"
if not exist "%PY%" (
 echo Python not found at %PY%
 echo Edit the PY path in this BAT if you moved ComfyUI.
 pause
 exit /b 1
)
"%PY%" -s "%~dp0BEAVIS_FIXED.py"
if errorlevel 1 pause
