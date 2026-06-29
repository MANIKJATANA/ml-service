#requires -Version 5.1
<#
.SYNOPSIS
    Bring the whole stack up in Docker (frontend + backend + ml-service + Postgres + Redis).

.DESCRIPTION
    Thin wrapper over `docker compose up --build`. Run from anywhere — it cd's to
    the repo root itself.

.PARAMETER Detached
    Run in the background (-d) and return immediately.

.PARAMETER NoBuild
    Skip rebuilding images (omits --build, which is otherwise on by default).

.EXAMPLE
    .\scripts\up.ps1            # build + run in the foreground (Ctrl+C to stop)
    .\scripts\up.ps1 -Detached  # build + run in the background
#>
[CmdletBinding()]
param(
    [switch]$Detached,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

# Repo root = parent of this script's folder.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Fail early with a clear message if the Docker daemon isn't reachable.
# In Windows PowerShell 5.1, a native command writing to stderr under
# $ErrorActionPreference='Stop' raises a terminating error that redirection
# alone won't swallow — so probe inside try/catch.
$dockerReachable = $true
try {
    & docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $dockerReachable = $false }
} catch {
    $dockerReachable = $false
}
if (-not $dockerReachable) {
    Write-Host "Docker daemon not reachable. Start Docker Desktop and retry." -ForegroundColor Red
    exit 1
}

$composeArgs = @("compose", "up")
if (-not $NoBuild) { $composeArgs += "--build" }
if ($Detached)     { $composeArgs += "-d" }

Write-Host "Starting stack: docker $($composeArgs -join ' ')" -ForegroundColor Cyan
& docker @composeArgs
exit $LASTEXITCODE
