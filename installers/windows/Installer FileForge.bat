@echo off
title Installation de FileForge
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo  L'installation a rencontre un probleme. Verifie ta connexion Internet puis relance.
)
echo.
pause
