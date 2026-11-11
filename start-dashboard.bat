@echo off
REM Starts the CyberNext dashboard inside WSL. First run installs dependencies.
REM "%~dp0." (with the dot) avoids the trailing backslash escaping the closing quote.
wsl.exe --cd "%~dp0." -e bash scripts/wsl_start.sh
if errorlevel 1 pause
