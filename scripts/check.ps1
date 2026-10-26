$ErrorActionPreference = 'Stop'
$loopdeskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $loopdeskRoot
# A fresh test directory avoids collisions and Windows temp directory restrictions.
$loopdeskTestPath = Join-Path '.local' ('pytest-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python -m pytest -q --basetemp=$loopdeskTestPath --junitxml=artifacts/pytest.xml
if ($LASTEXITCODE -ne 0) { throw 'Automated tests failed.' }
