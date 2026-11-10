@echo off
rem Starts Run Coach (if it isn't already running) and opens it in your browser.
cd /d "%~dp0"
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)) { Start-Process python -ArgumentList 'app.py' -WindowStyle Minimized }"
ping -n 4 127.0.0.1 >nul
start "" http://127.0.0.1:5000
