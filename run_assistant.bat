@echo off
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
    echo Не найдено виртуальное окружение .venv.
    echo Сначала выполните установку зависимостей из docs\gigachat_host_061.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "src\interfaces\gigachat\host.py" %*
if errorlevel 1 pause
