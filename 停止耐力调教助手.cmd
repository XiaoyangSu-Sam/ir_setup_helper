@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" start "" ".venv\Scripts\pythonw.exe" "%~dp0launch.py" --stop
