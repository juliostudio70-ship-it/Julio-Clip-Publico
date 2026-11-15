@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python\python.exe" (
  echo Falta el Python incluido. Extrae TODO el ZIP antes de abrir el programa.
  pause
  exit /b 1
)
"runtime\python\python.exe" -I "iniciar_windows.py" %*
if errorlevel 1 (
  echo Consulta LEEME-WINDOWS.md o ejecuta Comprobar-Equipo.cmd.
  pause
  exit /b 1
)
