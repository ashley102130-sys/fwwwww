if (!(Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
}

. .\.venv\Scripts\Activate.ps1
python copy_bot