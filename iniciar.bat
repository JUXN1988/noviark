@echo off
chcp 65001 >nul
title Noviark
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  No se encontro Python. Instala Python 3.10 o superior desde https://www.python.org/downloads/
  echo  IMPORTANTE: marca la casilla "Add Python to PATH" al instalar.
  echo.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo  Tu Python es muy antiguo. Instala Python 3.10 o superior.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo  Preparando el programa por primera vez, espera un momento...
  python -m venv .venv
)

".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo  Error instalando dependencias. Revisa tu conexion a internet.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" noviq_app.py
exit /b 0
REM
