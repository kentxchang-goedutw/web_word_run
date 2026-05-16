@echo off
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

python -m pip install -q -r requirements.txt
python desktop_marquee_v3.py

if %errorlevel% neq 0 (
    pause
)
