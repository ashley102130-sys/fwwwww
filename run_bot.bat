@echo off
setlocal
cd /d %~dp0
if not exist ".venv" (
    echo 正在建立虛擬環境...
    python -m venv .venv
    echo 正在安裝必要套件...
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo 啟動中...
call .\.venv\Scripts\activate.bat
python copy_bot
pause
