@echo off
REM Runs the MIU-LRSES reminder processor once. Use it from Windows Task Scheduler (see docs\REMINDERS.md).
REM Output is appended to logs\reminders.log in the project folder.
cd /d "%~dp0.."
if not exist logs mkdir logs
echo ===== %date% %time% ===== >> logs\reminders.log
call venv\Scripts\activate.bat
python manage.py process_reminders >> logs\reminders.log 2>&1
