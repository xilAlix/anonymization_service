@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Python virtual environment .venv was not found.
    echo Create it with: py -3.14 -m venv .venv
    echo Then install dependencies with: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    endlocal
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -u "%~dp0src\interfaces\gigachat\host.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
endlocal & exit /b %EXIT_CODE%
