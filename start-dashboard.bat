@echo off
REM Starts the CyberNext dashboard inside WSL. First run installs dependencies.
wsl.exe --cd "%~dp0" -e bash scripts/wsl_start.sh
if errorlevel 1 pause
