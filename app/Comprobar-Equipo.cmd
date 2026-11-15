@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python\python.exe" (
  echo Extrae TODO el ZIP. No ejecutes este archivo desde dentro del comprimido.
  pause
  exit /b 1
)
"runtime\python\python.exe" -I "comprobar_windows.py" --media
set "JULIO_CHECK_RESULT=%ERRORLEVEL%"
pause
exit /b %JULIO_CHECK_RESULT%
