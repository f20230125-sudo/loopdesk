$ErrorActionPreference = 'Stop'
$loopdeskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $loopdeskRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
    .venv/Scripts/python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
.venv/Scripts/python -m flask --app app migrate
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
.venv/Scripts/python app.py
