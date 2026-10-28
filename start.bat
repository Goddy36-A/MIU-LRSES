@echo off
REM Double-click this file. First time: sets everything up. Every time: starts MIU-LRSES in your browser.
setlocal
cd /d "%~dp0"
title MIU-LRSES

if not exist ".setup_done" (
  set "MIU_NO_PAUSE=1"
  call "%~dp0setup.bat"
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

if not exist "venv\Scripts\python.exe" (
  echo The Python environment is missing. Delete the file .setup_done and double-click start.bat again.
  pause
  exit /b 1
)

"venv\Scripts\python.exe" run_server.py %*
if errorlevel 1 (
  echo.
  echo MIU-LRSES stopped with an error. Read the message above.
  pause
)
exit /b 0
