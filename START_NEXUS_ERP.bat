@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Run INSTALL_NEXUS_ERP.bat first.
  pause
  exit /b 1
)
echo Starting Nexus ERP at http://127.0.0.1:8000
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload
pause
