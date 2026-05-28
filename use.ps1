if (!(Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
}

. .\.venv\Scripts\Activate.ps1

if (Test-Path "copy_bot.py") {
    python copy_bot.py
}
else {
    Write-Host "Error: copy_bot.py not found!" -ForegroundColor Red
}
