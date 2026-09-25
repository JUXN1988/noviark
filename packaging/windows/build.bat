@echo off
REM ============================================================
REM  Noviark - crea el instalador de Windows
REM  Resultado: dist\Noviark-Setup-Windows.exe (instalador) y dist\Noviark-Windows-portable.zip
REM  Requisitos: Python 3.10+ (https://python.org) e Inno Setup 6 (https://jrsoftware.org/isdl.php)
REM  El script instala Inno Setup solo con winget si no lo encuentra.
REM ============================================================
setlocal
cd /d "%~dp0\..\.."
echo [1/4] Preparando entorno de compilacion...
if not exist .build-venv\Scripts\python.exe ( py -3 -m venv .build-venv || python -m venv .build-venv )
.build-venv\Scripts\python -m pip install -q --upgrade pip
.build-venv\Scripts\python -m pip install -q -r packaging\requirements-build.txt || goto :error
echo [2/4] Compilando Noviark.exe con PyInstaller...
.build-venv\Scripts\python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\noviq.spec || goto :error
echo [3/4] Version portable (zip)...
powershell -NoProfile -Command "Compress-Archive -Force -Path dist\Noviark\* -DestinationPath dist\Noviark-Windows-portable.zip"
echo [4/4] Creando el instalador con Inno Setup...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo Inno Setup no esta instalado: lo instalo con winget...
  winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
  set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
)
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% ( echo No encontre Inno Setup. El programa portable esta en dist\Noviark & goto :fin )
%ISCC% /Q packaging\windows\noviq.iss || goto :error
echo.
echo LISTO: dist\Noviark-Setup-Windows.exe
goto :fin
:error
echo.
echo ERROR durante la compilacion. Revisa los mensajes de arriba.
exit /b 1
:fin
endlocal
