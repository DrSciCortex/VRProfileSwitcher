@echo off
cd /d "%~dp0"

:: Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

:: Install dependencies if needed
python -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    python -m pip install -r requirements.txt
)

python -c "import psutil" >nul 2>&1
if errorlevel 1 (
    echo Installing psutil...
    python -m pip install psutil
)

:: Launch
python main.py
