@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0.local\temp"
set "TMP=%~dp0.local\temp"
set "TMPDIR=%~dp0.local\temp"
set "PYTHONPYCACHEPREFIX=%~dp0.local\pycache"
set "PIP_CACHE_DIR=%~dp0.local\pip-cache"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
if not exist ".local\temp" mkdir ".local\temp"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
if exist ".local\wheels" (
  .venv\Scripts\python.exe -m pip install --no-index --find-links ".local\wheels" -r requirements.txt
) else (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
if errorlevel 1 goto failed
echo.
echo LoopDesk will open at http://127.0.0.1:5055
echo Use fictional data. Press Ctrl+C in this window to stop.
.venv\Scripts\python.exe scripts\manage.py run
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo LoopDesk could not start. See the error above and README.md.
pause
exit /b 1
