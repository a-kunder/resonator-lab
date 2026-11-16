@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" launch_power_gui.py
if errorlevel 1 (
  echo Resonator Lab exited with an error. See above.
  pause
  exit /b 1
)
