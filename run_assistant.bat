@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
    echo Не найдено виртуальное окружение .venv.
    echo Сначала выполните установку зависимостей из docs\gigachat_host_062.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u "src\interfaces\gigachat\host.py" %*
if errorlevel 1 pause
