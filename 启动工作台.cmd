@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
start "" http://127.0.0.1:8793
python -m xhs_scout.cli serve
