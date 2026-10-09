@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
python -m xhs_scout.cli capture-once
pause
