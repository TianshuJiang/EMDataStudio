@echo off
REM ── Quick launcher for EMDataStudio ──────────────────────────────────────
call conda activate EMDataStudio
cd /d "%~dp0.."
python main.py
pause
