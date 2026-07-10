#requires -Version 5.1
<#
.SYNOPSIS
    Local pre-commit gate: ruff + mypy + the layering invariant + pytest.

.DESCRIPTION
    Mirrors the GitHub Actions `check` job so failures surface before pushing.
    On Windows the Linux-only heavy deps (insightface/decord) are absent by
    design, so their adapter tests skip - everything else runs. Exits non-zero
    on the first failing step.

.EXAMPLE
    .\scripts\check.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -Path $repoRoot

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Invoke-Step "ruff check" { uv run ruff check . }
Invoke-Step "mypy" { uv run mypy . }

# Layering invariant (architecture section 5): no concrete ML/IO lib in the pure layers.
Write-Host "==> layering invariant" -ForegroundColor Cyan
$pureDirs = @(
    "services/ml_service/src/ml_service/domain",
    "services/ml_service/src/ml_service/orchestration"
)
$hits = Select-String -Path (Get-ChildItem -Recurse -Filter *.py -Path $pureDirs).FullName `
    -Pattern 'import faiss|import cv2|import insightface|import boto3'
if ($hits) {
    Write-Host "FAILED: concrete ML/IO import found in a pure layer" -ForegroundColor Red
    $hits | ForEach-Object { Write-Host $_.Line }
    exit 1
}

# Backend layering (decisions/0022): no concrete IO lib in backend domain/services.
# tests/test_layering.py is the thorough AST gate; this is the fast-fail mirror.
$bePureDirs = @(
    "services/backend/src/backend/domain",
    "services/backend/src/backend/services"
) | Where-Object { Test-Path $_ }
if ($bePureDirs) {
    $beHits = Select-String -Path (Get-ChildItem -Recurse -Filter *.py -Path $bePureDirs).FullName `
        -Pattern '(from|import)\s+(sqlalchemy|asyncpg|redis|httpx|supabase|fastapi|passlib|jwt|argon2)'
    if ($beHits) {
        Write-Host "FAILED: concrete IO import found in a backend pure layer" -ForegroundColor Red
        $beHits | ForEach-Object { Write-Host $_.Line }
        exit 1
    }
}

Invoke-Step "pytest" { uv run pytest }

Write-Host "All checks passed." -ForegroundColor Green
