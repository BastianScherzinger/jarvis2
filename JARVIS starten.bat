@echo off
title JARVIS LeadHunter
cd /d "%USERPROFILE%\Desktop\jarvis2"

if not exist "start.py" (
    echo [FEHLER] start.py nicht gefunden in: %CD%
    echo Bitte sicherstellen, dass JARVIS in Desktop\jarvis2\ liegt.
    pause
    exit /b 1
)

python start.py
if errorlevel 1 (
    echo.
    echo [FEHLER] JARVIS wurde mit einem Fehler beendet.
    pause
)
