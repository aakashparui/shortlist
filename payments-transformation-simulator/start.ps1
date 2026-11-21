# Start the Payments Transformation Simulator locally (backend + frontend).
#
#   .\start.ps1            start both
#   .\start.ps1 -Reset     drop the local SQLite database first
#
# Requires Python 3.11+ and Node 20+. Nothing else: the default database is
# SQLite and is created on first start.
#
# Pass -Python <path> to choose an interpreter explicitly.

[CmdletBinding()]
param(
    [switch]$Reset,
    [string]$Python,
    [int]$ApiPort = 8000,
    [int]$UiPort = 5173
)

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$pyMinMinor = 11

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Warn($message) { Write-Host "==> $message" -ForegroundColor Yellow }

# A precondition failure is the user's problem to fix, not a bug to report, so
# it prints one red line and exits rather than throwing a PowerShell stack
# trace over the message that matters.
function Write-Fail($message) {
    Write-Host "==> $message" -ForegroundColor Red
    exit 1
}

# Stop-Process kills one process. npm.cmd spawns node, so stopping the launcher
# alone orphans the dev server, which goes on holding the port -- the next start
# then silently binds 5174 while the banner still advertises 5173. taskkill /T
# takes the whole tree.
function Stop-ProcessTree($proc) {
    if (-not $proc) { return }
    if ($proc.HasExited) { return }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $null = & taskkill.exe '/PID' $proc.Id '/T' '/F' 2>&1
    } catch {
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch { }
    } finally {
        $ErrorActionPreference = $previous
    }
}

# --- interpreter discovery -------------------------------------------------
# Windows ships "App Execution Alias" stubs for python/python3: shims that
# resolve through Get-Command, print "Python was not found; run without
# arguments to install from the Microsoft Store" and exit non-zero. Resolving a
# name therefore proves nothing, so each candidate is proved by *running* it.
# That also rejects an interpreter that is real but too old (an Anaconda 3.9
# earlier on PATH, say).
function Resolve-PythonCandidate {
    param([string]$Exe, [string[]]$Prefix = @())

    # A native command's stderr becomes a terminating NativeCommandError under
    # $ErrorActionPreference = 'Stop', so the stub's complaint would throw
    # instead of simply failing the probe. Relax it for the probe only.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # The probe deliberately contains no quote characters. PowerShell 5.1
        # strips embedded double quotes when it builds a native command line, so
        # the obvious 'print("%d.%d" % sys.version_info[:2])' reaches Python as
        # print(%d.%d % ...) and dies with a SyntaxError -- which the probe would
        # then misreport as "no working interpreter". Encoding the version as one
        # integer avoids needing any string literal.
        $code = 'import sys; print(sys.version_info[0]*100+sys.version_info[1])'
        $output = & $Exe @Prefix '-c' $code 2>&1
        if ($LASTEXITCODE -ne 0) { return $null }
        $text = ($output | Out-String).Trim()
        if ($text -notmatch '^\d+$') { return $null }
        $encoded = [int]$text
        $major = [math]::Floor($encoded / 100)
        $minor = $encoded % 100
        if ($major -ne 3 -or $minor -lt $pyMinMinor) { return $null }
        return [pscustomobject]@{ Exe = $Exe; Prefix = $Prefix; Version = "$major.$minor" }
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Find-Python {
    if ($Python) {
        $explicit = Resolve-PythonCandidate -Exe $Python
        if ($explicit) { return $explicit }
        Write-Fail "-Python '$Python' is not a working Python 3.$pyMinMinor+ interpreter."
    }
    foreach ($name in @('python3', 'python')) {
        if (Get-Command $name -ErrorAction SilentlyContinue) {
            $found = Resolve-PythonCandidate -Exe $name
            if ($found) { return $found }
        }
    }
    # The Windows launcher reaches interpreters that are not on PATH at all.
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        foreach ($tag in @('-3.14', '-3.13', '-3.12', '-3.11', '-3')) {
            $found = Resolve-PythonCandidate -Exe 'py' -Prefix @($tag)
            if ($found) { return $found }
        }
    }
    return $null
}

$interpreter = Find-Python
if (-not $interpreter) {
    $hint = ''
    if (Get-Command 'python' -ErrorAction SilentlyContinue) {
        $hint = "`n`n  'python' does resolve here but does not run. On Windows that is almost" +
                "`n  always the Microsoft Store alias stub. Either install Python from" +
                "`n  python.org, or turn the stub off under Settings > Apps >" +
                "`n  Advanced app settings > App execution aliases."
    }
    Write-Fail ("No working Python 3.$pyMinMinor+ interpreter was found.`n`n" +
           "  Tried: -Python, python3, python, py -3.x`n" +
           "  Install Python 3.$pyMinMinor or newer, or point the script at one:`n" +
           "    .\start.ps1 -Python C:\path\to\python.exe$hint")
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Fail 'Node 20+ is required but was not found on PATH.'
}
# `npm` resolves to several things on Windows, including an extensionless Unix
# shell script. Start-Process picks that one and fails with "%1 is not a valid
# Win32 application", so the launcher has to be named explicitly.
$npm = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
if (-not $npm) { Write-Fail 'npm.cmd is required but was not found on PATH.' }
$npmPath = $npm.Source

Write-Step "Using Python $($interpreter.Version) ($($interpreter.Exe) $($interpreter.Prefix -join ' '))"

if ($Reset) {
    Write-Warn 'Removing the local SQLite database'
    Get-ChildItem -Path (Join-Path $backend 'data') -Filter 'simulator.db*' -ErrorAction SilentlyContinue |
        Remove-Item -Force
}

# --- backend ---------------------------------------------------------------
$venv = Join-Path $backend '.venv'
if (-not (Test-Path $venv)) {
    Write-Step 'Creating the backend virtual environment'
    & $interpreter.Exe @($interpreter.Prefix) '-m' 'venv' $venv
    if ($LASTEXITCODE -ne 0) { Write-Fail "Creating the virtual environment at $venv failed." }
}
$venvPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    $venvPython = Join-Path $venv 'bin/python'
}
if (-not (Test-Path $venvPython)) {
    Write-Fail "The virtual environment at $venv has no interpreter. Delete it and re-run."
}

# An existing venv may well be a different version from the interpreter found
# above, which is only used to *create* one. Report what actually runs the API.
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $venvVersion = (& $venvPython '-c' 'import sys; print(sys.version_info[0]*10000+sys.version_info[1]*100+sys.version_info[2])' 2>&1 | Out-String).Trim()
} finally { $ErrorActionPreference = $previous }
if ($venvVersion -match '^\d+$') {
    $n = [int]$venvVersion
    Write-Step ("Backend environment: Python {0}.{1}.{2}" -f [math]::Floor($n / 10000), [math]::Floor(($n % 10000) / 100), ($n % 100))
}

# A venv made by `uv venv` (or `python -m venv --without-pip`) has no pip, so an
# existing environment cannot be assumed to have one. Probed quietly so the
# "No module named pip" complaint does not land on top of our own message.
$hasPip = $false
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $null = & $venvPython -m pip --version 2>&1
    $hasPip = ($LASTEXITCODE -eq 0)
} finally { $ErrorActionPreference = $previous }

if (-not $hasPip) {
    Write-Step 'Bootstrapping pip into the existing virtual environment'
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $null = & $venvPython -m ensurepip --upgrade 2>&1
        $bootstrapped = ($LASTEXITCODE -eq 0)
    } finally { $ErrorActionPreference = $previous }
    if (-not $bootstrapped) {
        Write-Fail "The virtual environment at $venv has no pip and ensurepip failed. Delete it and re-run."
    }
}

Write-Step 'Installing backend dependencies'
& $venvPython -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Fail 'Upgrading pip failed.' }
# Installed from inside $backend with a relative requirement, so the project
# path never has to survive quoting as part of a "path[extras]" argument.
Push-Location $backend
try {
    & $venvPython -m pip install --quiet -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { Write-Fail 'Installing the backend dependencies failed.' }
} finally { Pop-Location }

# --- frontend --------------------------------------------------------------
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Step 'Installing frontend dependencies'
    Push-Location $frontend
    try {
        & $npmPath install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { Write-Fail 'npm install failed.' }
    } finally { Pop-Location }
}

$api = $null
$ui = $null
try {
    Write-Step "Starting the API on http://localhost:$ApiPort"
    $api = Start-Process -FilePath $venvPython `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$ApiPort") `
        -WorkingDirectory $backend -PassThru -NoNewWindow

    Write-Step 'Waiting for the API to become ready (first run seeds the demo book)'
    $ready = $false
    foreach ($attempt in 1..90) {
        if ($api.HasExited) {
            throw "The API exited with code $($api.ExitCode) before it became ready. Its output is above."
        }
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            # not up yet
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "The API did not answer http://127.0.0.1:$ApiPort/health within 90s."
    }
    Write-Step 'API is ready'

    Write-Step "Starting the console on http://localhost:$UiPort"
    $ui = Start-Process -FilePath $npmPath `
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

    # Stop as soon as *either* process does, so a crashed API cannot leave a
    # half-running stack that still looks healthy.
    while (-not $api.HasExited -and -not $ui.HasExited) { Start-Sleep -Seconds 1 }
} catch {
    # Thrown rather than Write-Fail'd so this finally still stops the servers.
    Write-Host "==> $($_.Exception.Message)" -ForegroundColor Red
    $startupFailed = $true
} finally {
    Write-Step 'Shutting down'
    foreach ($proc in @($ui, $api)) {
        Stop-ProcessTree $proc
    }
}

if ($startupFailed) { exit 1 }
