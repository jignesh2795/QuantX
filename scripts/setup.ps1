param(
    [switch]$NoPythonInstall
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not installed. Install it with: winget install --id=astral-sh.uv -e"
}

if (-not $NoPythonInstall) {
    uv python install
}

uv sync --dev --extra dhan
uv run python --version
Write-Host "QuantX uv environment is ready."
