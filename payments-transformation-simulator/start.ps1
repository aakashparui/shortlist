# Start the Payments Transformation Simulator locally (backend + frontend).
#
#   .\start.ps1            start both
#   .\start.ps1 -Reset     drop the local SQLite database first
#
# Requires Python 3.11+ and Node 20+. Nothing else: the default database is
# SQLite and is created on first start.

[CmdletBinding()]
param(
    [switch]$Reset,
    [int]$ApiPort = 8000,
    [int]$UiPort = 5173
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Warn($message) { Write-Host "==> $message" -ForegroundColor Yellow }

$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) { throw 'Python 3.11+ is required but was not found on PATH.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node 20+ is required but was not found on PATH.'
}

if ($Reset) {
    Write-Warn 'Removing the local SQLite database'
    Get-ChildItem -Path (Join-Path $backend 'data') -Filter 'simulator.db*' -ErrorAction SilentlyContinue |
        Remove-Item -Force
}

# --- backend ---------------------------------------------------------------
$venv = Join-Path $backend '.venv'
if (-not (Test-Path $venv)) {
    Write-Step 'Creating the backend virtual environment'
    & python -m venv $venv
}
$venvPython = Join-Path $venv 'Scripts\python.exe'

Write-Step 'Installing backend dependencies'
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e "$backend[dev]"

# --- frontend --------------------------------------------------------------
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Step 'Installing frontend dependencies'
    Push-Location $frontend
    try { & npm install --no-audit --no-fund } finally { Pop-Location }
}

$apiJob = $null
$uiJob = $null
try {
    Write-Step "Starting the API on http://localhost:$ApiPort"
    $apiJob = Start-Process -FilePath $venvPython `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$ApiPort") `
        -WorkingDirectory $backend -PassThru -NoNewWindow

    Write-Step 'Waiting for the API to become ready (first run seeds the demo book)'
    $ready = $false
    foreach ($attempt in 1..90) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if ($ready) { Write-Step 'API is ready' } else { Write-Warn 'API did not report ready; continuing anyway' }

    Write-Step "Starting the console on http://localhost:$UiPort"
    $uiJob = Start-Process -FilePath 'npm' `
        -ArgumentList @('run', 'dev', '--', '--port', "$UiPort") `
        -WorkingDirectory $frontend -PassThru -NoNewWindow

    Write-Host ''
    Write-Host '  Payments Transformation Simulator'
    Write-Host '  ---------------------------------'
    Write-Host "  Console   http://localhost:$UiPort"
    Write-Host "  API docs  http://localhost:$ApiPort/docs"
    Write-Host "  Health    http://localhost:$ApiPort/health"
    Write-Host ''
    Write-Host '  Simulated environment. All data is fictional.'
    Write-Host '  Press Ctrl+C to stop both.'
    Write-Host ''

    Wait-Process -Id $apiJob.Id
} finally {
    Write-Step 'Shutting down'
    foreach ($proc in @($apiJob, $uiJob)) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
