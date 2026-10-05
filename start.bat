@echo off
rem Double-click to start Bullion Register on this computer.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up...
  python -m venv .venv || "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" run.py %*
pause
