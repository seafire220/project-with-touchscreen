@echo off
rem Start Character Studio, the character maker, and open it in the browser (Windows).
rem Double-click this file. The first run sets up the studio's own Python environment in
rem %USERPROFILE%\.character-studio (several GB with PyTorch; it takes a while). Later runs start at once.
rem Needs Python 3.10 or newer from https://www.python.org/downloads/ . Options are passed on to app.py
rem (for example --port 8771 or --no-browser). Closing this window stops the studio.
setlocal
set "HERE=%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" in the installer^), then double-click start.bat again.
  pause
  exit /b 1
)
%PY% "%HERE%launch.py" %*
if errorlevel 1 (
  echo.
  echo Character Studio stopped with a problem ^(shown above^).
  pause
)
endlocal
