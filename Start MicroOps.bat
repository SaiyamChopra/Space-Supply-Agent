@echo off
cd /d "%~dp0"
python run.py
if errorlevel 1 (
  echo.
  echo MicroOps could not start. Install Python 3.10 or newer and try again.
  pause
)
