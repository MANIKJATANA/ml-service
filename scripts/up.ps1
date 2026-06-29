#requires -Version 5.1
<#
.SYNOPSIS
    Bring the stack up in Docker. App services (frontend + backend + ml-service)
    run attached in the foreground; the backing services (Postgres + Redis) run
    detached and KEEP running.

.DESCRIPTION
    Press Ctrl+C to stop the app services (frontend, backend, ml-service) only.
    Postgres and Redis stay up in the background so you don't lose DB/queue state
    between restarts. Stop everything with `docker compose down`.

.PARAMETER Detached
    Also run the app services in the background instead of attaching. Nothing to
    Ctrl+C; use `docker compose down` (or `stop`) to bring them down.

.PARAMETER NoBuild
    Skip rebuilding the app images (omits --build, which is otherwise on).

.EXAMPLE
    .\scripts\up.ps1            # infra detached; apps in foreground (Ctrl+C stops apps)
    .\scripts\up.ps1 -Detached  # everything in the background
#>
[CmdletBinding()]
param(
    [switch]$Detached,
    [switch]$NoBuild
)

# NOTE: do not set $ErrorActionPreference = 'Stop'. In Windows PowerShell 5.1
# that turns any native-command stderr write into a terminating error, and
# `docker compose` streams normal progress/logs to stderr, which would kill the
# run (and break Ctrl+C handling). We judge success by exit code instead.

# Repo root = parent of this script's folder.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -Path $repoRoot -ErrorAction Stop

# Force Compose's classic builder. Its "bake" delegation can fail with
# 'failed to solve: image "...": already exists' when rebuilding images that
# already exist in Docker Desktop's containerd image store.
$env:COMPOSE_BAKE = "false"

# Fail early with a clear message if the Docker daemon isn't reachable.
docker info 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker daemon not reachable. Start Docker Desktop and retry." -ForegroundColor Red
    exit 1
}

$infra = @("postgres", "redis")          # stay running in the background
$apps  = @("frontend", "backend", "ml-service")

# 1) Backing services: always detached so they survive Ctrl+C on the apps.
Write-Host "Starting backing services (kept running): $($infra -join ', ')" -ForegroundColor Cyan
docker compose up -d @infra
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 2) App services. --no-deps so Compose won't also stop postgres/redis on Ctrl+C.
$appArgs = @("compose", "up", "--no-deps")
if (-not $NoBuild) { $appArgs += "--build" }
if ($Detached)     { $appArgs += "-d" }
$appArgs += $apps

if ($Detached) {
    Write-Host "Starting app services (detached): $($apps -join ', ')" -ForegroundColor Cyan
} else {
    Write-Host "Starting app services (foreground). Press Ctrl+C to stop them - Postgres/Redis stay up." -ForegroundColor Cyan
    Write-Host "Stop everything with: docker compose down" -ForegroundColor DarkGray
}

& docker @appArgs
exit $LASTEXITCODE
