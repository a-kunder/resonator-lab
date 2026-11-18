@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -c "import sys, tkinter; assert sys.version_info >= (3,9), 'Python 3.9 or newer is required'"
if errorlevel 1 goto failed
py -3 -m venv .venv
if errorlevel 1 goto failed
goto install
:use_python
python -c "import sys, tkinter; assert sys.version_info >= (3,9), 'Python 3.9 or newer is required'"
if errorlevel 1 goto failed
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto failed
echo.
echo Setup complete. Double-click launch_power_windows.bat to open Resonator Lab.
echo Hardware requires NI-VISA or Keysight IO Libraries. See WINDOWS_SETUP.md.
pause
exit /b 0
:failed
echo.
echo Setup failed. Read the error above and see WINDOWS_SETUP.md.
echo Install Python 3.9 or newer with pip and Tcl/Tk, then retry.
pause
exit /b 1
