@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение...
    py -m venv .venv
    if errorlevel 1 (
        echo Не удалось создать .venv. Проверьте, что Python 3.10+ установлен.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Не удалось установить зависимости.
        pause
        exit /b 1
    )
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Создан файл .env.
    echo Откройте его и вставьте DISCORD_TOKEN, затем запустите run.bat снова.
    notepad ".env"
    pause
    exit /b 0
)

".venv\Scripts\python.exe" bot.py
pause
