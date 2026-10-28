@echo off
REM Runs the automated test suite.
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Run start.bat once first to set things up.
  pause
  exit /b 1
)
"venv\Scripts\python.exe" manage.py test
echo.
pause
