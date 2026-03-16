# 1. Check if virtual environment exists, create if not
if (!(Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment..."
    python -m venv .venv
}

# 2. Activate environment
.\.venv\Scripts\Activate.ps1

# 3. Upgrade pip and install requirements
Write-Host "Updating pip and installing requirements..."
pip install -q --upgrade pip
if (Test-Path "requirements.txt") {
    pip install -q -r requirements.txt
}

# 4. Show success message
Write-Host "==============================================="
Write-Host "  Python bot development environment loaded"
$pyver = python --version
Write-Host "  Python version : $pyver"
Write-Host ""
Write-Host "  Common commands:"
Write-Host "    python your_script.py"
Write-Host "    ipython               # interactive debug"
Write-Host "    black .               # format code"
Write-Host "    ruff check .          # check code"
Write-Host ""
Write-Host "  It's recommended to put token in .env file"
Write-Host "  Example: DISCORD_TOKEN=your_token"
Write-Host "==============================================="
