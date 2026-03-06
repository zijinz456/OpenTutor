#Requires -Version 5.1
<#
.SYNOPSIS
    OpenTutor one-click setup for Windows.
.DESCRIPTION
    Checks prerequisites, creates a Python virtual environment, sets up the
    database, installs dependencies, and starts the API + Web dev servers.

    Usage:
        .\scripts\quickstart.ps1
        .\scripts\quickstart.ps1 -SkipWSLCheck
#>
[CmdletBinding()]
param(
    [switch]$SkipWSLCheck
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$ApiDir = Join-Path $RootDir "apps\api"
$WebDir = Join-Path $RootDir "apps\web"
$EnvFile = Join-Path $RootDir ".env"
$VenvDir = Join-Path $ApiDir ".venv"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step($msg) {
    Write-Host "`n== $msg ==" -ForegroundColor Cyan
}
function Write-Log($msg) {
    Write-Host $msg
}
function Write-Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}
function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path $Path)) {
        return ""
    }

    foreach ($line in Get-Content $Path) {
        if ($line -match "^\s*#") {
            continue
        }
        if ($line -match "^\s*$Name\s*=\s*(.*)\s*$") {
            return $matches[1].Trim().Trim("'`"")
        }
    }
    return ""
}
function Resolve-SqlitePath {
    param([string]$DatabaseUrl)

    if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
        return Join-Path $HOME ".opentutor\data.db"
    }

    $path = $DatabaseUrl
    foreach ($prefix in @("sqlite+aiosqlite:///", "sqlite:///")) {
        if ($path.StartsWith($prefix)) {
            $path = $path.Substring($prefix.Length)
            break
        }
    }
    if ($path.StartsWith("~/")) {
        $path = Join-Path $HOME $path.Substring(2)
    } elseif ($path -match "^/[A-Za-z]:/") {
        $path = $path.Substring(1)
    }
    $nativePath = $path -replace "/", [IO.Path]::DirectorySeparatorChar
    return [IO.Path]::GetFullPath($nativePath)
}

# ---------------------------------------------------------------------------
# 0. WSL2 hint
# ---------------------------------------------------------------------------
if (-not $SkipWSLCheck) {
    try {
        $wslOutput = wsl --list --quiet 2>$null
        if ($LASTEXITCODE -eq 0 -and $wslOutput) {
            Write-Host ""
            Write-Host "WSL2 detected. For the best experience you can also run OpenTutor inside WSL2:" -ForegroundColor Yellow
            Write-Host "  wsl -- bash -c 'cd $(($RootDir -replace '\\','/') -replace '^([A-Z]):','/mnt/$1'.ToLower()) && bash scripts/quickstart.sh'"
            Write-Host ""
            Write-Host "Continuing with native Windows setup..." -ForegroundColor Gray
            Write-Host ""
        }
    } catch { }
}

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
Write-Step "Checking prerequisites"

# Node.js
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Fail "Node.js not found. Download from https://nodejs.org/ (v20+ recommended)"
}
Write-Log "  Node $(node --version)"

# npm
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Fail "npm not found. Install Node.js from https://nodejs.org/"
}

# Python 3.11 — try several candidate commands
$PyBin = $null
foreach ($candidate in @("python3.11", "python3", "python")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            $ver = & $cmd.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -eq "3.11") {
                $PyBin = $cmd.Source
                break
            }
        } catch { }
    }
}
# Windows Python Launcher (py -3.11)
if (-not $PyBin -and (Get-Command py -ErrorAction SilentlyContinue)) {
    try {
        $ver = py -3.11 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver -eq "3.11") {
            # Use a wrapper-friendly approach: store the launcher args
            $PyBin = "py"
            $PyBinArgs = @("-3.11")
        }
    } catch { }
}
if (-not $PyBin) {
    Write-Fail "Python 3.11 not found. Download from https://www.python.org/downloads/release/python-3110/ (check 'Add to PATH')"
}
Write-Log "  Python 3.11 found"

# Helper to invoke python consistently
function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments)]$Args_)
    if ($PyBinArgs) {
        & $PyBin @PyBinArgs @Args_
    } else {
        & $PyBin @Args_
    }
}

# curl (built into Windows 10+)
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Write-Fail "curl.exe not found (should be built into Windows 10+)"
}

# ---------------------------------------------------------------------------
# 2. Environment file
# ---------------------------------------------------------------------------
Write-Step "Environment configuration"

if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $RootDir ".env.example") $EnvFile
    Write-Log "  .env created from .env.example"
    Write-Log "  Connect Ollama or add an API key for AI features."
} else {
    Write-Log "  .env already exists"
}

$DatabaseUrl = Get-DotEnvValue -Path $EnvFile -Name "DATABASE_URL"
if (-not [string]::IsNullOrWhiteSpace($DatabaseUrl) -and -not $DatabaseUrl.StartsWith("sqlite")) {
    $DbMode = "postgresql"
    $DbDisplay = $DatabaseUrl
} else {
    $DbMode = "sqlite"
    if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
        $DbDisplay = "sqlite+aiosqlite:///$HOME/.opentutor/data.db"
    } else {
        $DbDisplay = $DatabaseUrl
    }
}
Write-Log "  Database mode: $DbMode"
Write-Log "  Database URL:  $DbDisplay"

# ---------------------------------------------------------------------------
# 3. Python virtual environment
# ---------------------------------------------------------------------------
Write-Step "Python environment"

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Log "  Creating virtual environment ..."
    Invoke-Python -m venv $VenvDir
}

Write-Log "  Installing Python dependencies ..."
& $VenvPip install -q -r (Join-Path $ApiDir "requirements-core.txt")
Write-Log "  Done"
Write-Log "  Optional integrations remain available via requirements-full.txt"

# ---------------------------------------------------------------------------
# 4. Database setup
# ---------------------------------------------------------------------------
Write-Step "Database"

if ($DbMode -eq "postgresql") {
    if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
        Write-Fail "PostgreSQL (psql) not found. Download from https://www.postgresql.org/download/windows/"
    }
    Write-Log "  psql found"

    $DbName = "opentutor"
    try {
        $uri = [Uri]$DatabaseUrl
        if ($uri.AbsolutePath) {
            $DbName = $uri.AbsolutePath.Trim("/")
        }
    } catch { }

    $pgReady = $false
    try {
        pg_isready -q 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $pgReady = $true }
    } catch { }
    if (-not $pgReady) {
        Write-Log "  PostgreSQL is not running. Attempting to start ..."
        try {
            $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($pgService -and $pgService.Status -ne "Running") {
                Start-Service $pgService.Name -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 3
            }
        } catch { }
        try {
            pg_isready -q 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $pgReady = $true }
        } catch { }
        if (-not $pgReady) {
            Write-Fail "PostgreSQL is not running. Start it via Services (services.msc), pg_ctl, or: Start-Service postgresql-x64-16"
        }
    }
    Write-Log "  PostgreSQL is running"

    $dbList = psql -lqt 2>$null
    if ($dbList -and ($dbList | Select-String -Pattern "\b$DbName\b" -Quiet)) {
        Write-Log "  Database '$DbName' already exists"
    } else {
        Write-Log "  Creating database '$DbName' ..."
        createdb $DbName 2>$null
    }

    psql -d $DbName -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Log "  Warning: Could not create pgvector extension. See https://github.com/pgvector/pgvector#windows"
    }
} else {
    $sqlitePath = Resolve-SqlitePath -DatabaseUrl $DatabaseUrl
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $sqlitePath) | Out-Null
    Write-Log "  Using SQLite lite mode at $sqlitePath"
    Write-Log "  PostgreSQL is not required for this quickstart."
}

# ---------------------------------------------------------------------------
# 5. Database migrations
# ---------------------------------------------------------------------------
if ($DbMode -eq "postgresql") {
    Write-Step "Running database migrations"

    Push-Location $ApiDir
    & $VenvPython -m alembic upgrade head
    Pop-Location
    Write-Log "  Migrations complete"
} else {
    Write-Step "Database bootstrap"
    Write-Log "  SQLite mode uses the app startup hooks to create tables and seed built-in data."
}

# ---------------------------------------------------------------------------
# 6. Frontend dependencies
# ---------------------------------------------------------------------------
Write-Step "Frontend dependencies"

Push-Location $WebDir
$needsInstall = $false
if (-not (Test-Path "node_modules")) {
    $needsInstall = $true
} else {
    $pkgTime = (Get-Item "package.json").LastWriteTime
    $lockFile = Get-Item "node_modules\.package-lock.json" -ErrorAction SilentlyContinue
    if (-not $lockFile -or $pkgTime -gt $lockFile.LastWriteTime) {
        $needsInstall = $true
    }
}
if ($needsInstall) {
    Write-Log "  Installing npm packages ..."
    npm install --no-audit --no-fund 2>&1 | Select-Object -Last 1
} else {
    Write-Log "  node_modules up to date"
}
Pop-Location

# ---------------------------------------------------------------------------
# 7. Launch services
# ---------------------------------------------------------------------------
Write-Step "Starting services"

Write-Log "  Starting API server (port 8000) ..."
$apiJob = Start-Job -ScriptBlock {
    param($venvPy, $apiDir_)
    Set-Location $apiDir_
    & $venvPy -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload 2>&1
} -ArgumentList $VenvPython, $ApiDir

Write-Log "  Starting Web server (port 3000) ..."
$webJob = Start-Job -ScriptBlock {
    param($webDir_)
    Set-Location $webDir_
    npm run dev 2>&1
} -ArgumentList $WebDir

# ---------------------------------------------------------------------------
# 8. Wait for readiness
# ---------------------------------------------------------------------------
Write-Step "Waiting for services to become ready"

$timeout = 60
$start = Get-Date
while ($true) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) { break }
    } catch { }
    if (((Get-Date) - $start).TotalSeconds -ge $timeout) {
        # Show any job errors before failing
        Receive-Job $apiJob -ErrorAction SilentlyContinue | Write-Host
        Write-Fail "API did not become ready within ${timeout}s"
    }
    Start-Sleep -Seconds 2
}
Write-Log "  API ready"

$start = Get-Date
while ($true) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) { break }
    } catch { }
    if (((Get-Date) - $start).TotalSeconds -ge $timeout) {
        Write-Fail "Web did not become ready within ${timeout}s"
    }
    Start-Sleep -Seconds 2
}
Write-Log "  Web ready"

# Check local beta readiness
$llmStatus = "unknown"
$databaseBackend = "unknown"
$localBetaReady = $false
$localBetaBlockers = @()
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8000/api/health" -ErrorAction SilentlyContinue
    $llmStatus = $health.llm_status
    if ($health.database_backend) {
        $databaseBackend = $health.database_backend
    }
    if ($null -ne $health.local_beta_ready) {
        $localBetaReady = [bool]$health.local_beta_ready
    }
    if ($health.local_beta_blockers) {
        $localBetaBlockers = @($health.local_beta_blockers)
    }
} catch { }

Write-Host ""
Write-Host "============================================"
Write-Host "  OpenTutor is running!"
Write-Host "  Web:    http://localhost:3000"
Write-Host "  API:    http://localhost:8000/api"
Write-Host "  Health: http://localhost:8000/api/health"
Write-Host "  DB:     $databaseBackend"
Write-Host ""
if ($llmStatus -eq "ready") {
    Write-Host "  LLM: ready"
} elseif ($llmStatus -eq "mock_fallback") {
    Write-Host "  LLM: not ready for beta (connect Ollama or add an API key)"
} else {
    Write-Host "  LLM: $llmStatus"
}
if ($localBetaReady) {
    Write-Host "  Local beta readiness: ready"
} else {
    $blockers = if ($localBetaBlockers.Count -gt 0) { $localBetaBlockers -join ", " } else { "unknown" }
    Write-Host "  Local beta readiness: blocked ($blockers)"
    Write-Host "  Tip: open Settings in the app and connect a real LLM provider."
}
Write-Host ""
Write-Host "  Press Ctrl+C to stop all services."
Write-Host "============================================"

# Keep running until Ctrl+C
try {
    while ($true) {
        # Surface any errors from background jobs
        Receive-Job $apiJob -ErrorAction SilentlyContinue | Out-Null
        Receive-Job $webJob -ErrorAction SilentlyContinue | Out-Null

        # Check if jobs have stopped unexpectedly
        if ($apiJob.State -eq "Failed") {
            Write-Host "API server stopped unexpectedly:" -ForegroundColor Red
            Receive-Job $apiJob
            break
        }
        if ($webJob.State -eq "Failed") {
            Write-Host "Web server stopped unexpectedly:" -ForegroundColor Red
            Receive-Job $webJob
            break
        }

        Start-Sleep -Seconds 3
    }
} finally {
    Write-Host "`nShutting down..."
    Stop-Job $apiJob, $webJob -ErrorAction SilentlyContinue
    Remove-Job $apiJob, $webJob -Force -ErrorAction SilentlyContinue
    Write-Host "Done."
}
