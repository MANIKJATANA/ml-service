#requires -Version 5.1
<#
.SYNOPSIS
    Local pre-commit gate: ruff + mypy + the layering invariant + pytest.

.DESCRIPTION
    Mirrors the GitHub Actions `check` job so failures surface before pushing.
    On Windows the Linux-only heavy deps (insightface/decord) are absent by
    design, so their adapter tests skip — everything else runs. Exits non-zero
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

# Layering invariant (architecture §5): no concrete ML/IO lib in the pure layers.
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

Invoke-Step "pytest" { uv run pytest }

Write-Host "All checks passed." -ForegroundColor Green
