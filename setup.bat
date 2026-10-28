@echo off
REM Sets up MIU-LRSES on this computer (safe to run again). Normally you only need start.bat.
setlocal
cd /d "%~dp0"
title MIU-LRSES setup

set "PYEXE="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYEXE=py -3"
if not defined PYEXE (
  python --version >nul 2>&1
  if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
  echo.
  echo Python was not found on this computer.
  echo 1. Download Python from https://www.python.org/downloads/
  echo 2. In the installer, TICK "Add python.exe to PATH", then click Install.
  echo 3. Close this window and double-click start.bat again.
  echo.
  pause
  exit /b 1
)

%PYEXE% setup_local.py %*
if errorlevel 1 (
  echo.
  echo Setup did not finish. Read the message above, fix it, then double-click start.bat again.
  if /i not "%MIU_NO_PAUSE%"=="1" pause
  exit /b 1
)
if /i not "%MIU_NO_PAUSE%"=="1" pause
exit /b 0
