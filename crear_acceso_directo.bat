@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Noviark.lnk'); $s.TargetPath='%~dp0iniciar.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0static\noviq.ico'; $s.WindowStyle=7; $s.Description='Noviark - agente de IA'; $s.Save()"
echo  Acceso directo "Noviark" creado en tu Escritorio.
pause
