@echo off
title GENESIS Imagine
cd /d "%~dp0"
echo Starting GENESIS Imagine at http://127.0.0.1:7865
where py >nul 2>nul
if %errorlevel%==0 (
  start "" http://127.0.0.1:7865
  py -m http.server 7865 --directory dist
) else (
  start "" http://127.0.0.1:7865
  python -m http.server 7865 --directory dist
)
pause
