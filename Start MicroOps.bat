@echo off
if /i not "%~1"=="--hidden" (
  start "" wscript.exe "%~dp0Start MicroOps.vbs"
  exit /b 0
)

cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv --system-site-packages
  if errorlevel 1 exit /b 1
)

if not exist ".venv\Lib\site-packages\flet\__init__.py" (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-index --find-links offline_packages flet==1.0.3 flet-desktop==1.0.3
  if errorlevel 1 exit /b 1
)

if not exist ".venv\Lib\site-packages\flet_desktop\app" mkdir ".venv\Lib\site-packages\flet_desktop\app"
copy /Y "offline_packages\flet-windows.zip" ".venv\Lib\site-packages\flet_desktop\app\flet-windows.zip" >nul
if errorlevel 1 exit /b 1

start "" ".venv\Scripts\pythonw.exe" run.py
exit /b 0
