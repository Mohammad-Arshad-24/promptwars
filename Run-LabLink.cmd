@echo off
setlocal
cd /d "%~dp0"
set "LABLINK_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "LABLINK_PYTHON=.venv\Scripts\python.exe"
echo Starting LabLink at http://127.0.0.1:8080
echo Open that address once the server reports it is running. Press Ctrl+C to stop.
"%LABLINK_PYTHON%" -m uvicorn lablink.main:app --host 127.0.0.1 --port 8080
if errorlevel 1 pause
