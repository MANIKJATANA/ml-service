#requires -Version 5.1
<#
.SYNOPSIS
    Sync missing env keys from .env.example into .env.

.DESCRIPTION
    Every active `KEY=` line present in .env.example but missing from .env is
    appended to .env, carrying the example's default/placeholder value. Commented
    and blank lines in .env.example are ignored, so intentionally-commented keys
    (e.g. ML_QUEUE_CONSUMER) are never added. Existing .env values are never
    touched or overwritten — real secrets already in .env stay as they are. Prints
    exactly which keys were added.

    Pairs with the working rule "Every new env var goes in .env.example" (CLAUDE.md):
    once a new var is documented in .env.example, this script propagates it to a
    developer's local .env.

.PARAMETER Check
    Dry run: report the missing keys and the fix command, but do not modify .env.
    Exit code 0 if .env is in sync, 1 if any keys are missing. Used by up.ps1.

.EXAMPLE
    .\scripts\sync-env.ps1          # add the missing keys to .env
    .\scripts\sync-env.ps1 -Check   # just report what's missing (no changes)
#>
[CmdletBinding()]
param([switch]$Check)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$examplePath = Join-Path $repoRoot '.env.example'
$envPath = Join-Path $repoRoot '.env'

if (-not (Test-Path $examplePath)) {
    Write-Host "[env-sync] .env.example not found at $examplePath" -ForegroundColor Red
    exit 2
}

# Matches an active assignment line; captures the key. Commented (#...) and blank
# lines never match, so they are skipped.
$keyRegex = '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*='

function Get-ActiveKeys([string]$path) {
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    if (Test-Path $path) {
        foreach ($line in Get-Content -LiteralPath $path) {
            if ($line -match $keyRegex) { [void]$set.Add($matches[1]) }
        }
    }
    return $set
}

$envKeys = Get-ActiveKeys $envPath

# Walk .env.example in order so the appended block preserves its layout.
$exampleCount = 0
$missing = New-Object System.Collections.ArrayList
foreach ($line in Get-Content -LiteralPath $examplePath) {
    if ($line -match $keyRegex) {
        $exampleCount++
        $key = $matches[1]
        if (-not $envKeys.Contains($key)) {
            [void]$missing.Add([pscustomobject]@{ Key = $key; Line = $line })
        }
    }
}

if ($missing.Count -eq 0) {
    Write-Host "[env-sync] .env is in sync with .env.example ($exampleCount keys)." -ForegroundColor Green
    exit 0
}

if ($Check) {
    Write-Host "[env-sync] .env is MISSING $($missing.Count) key(s) documented in .env.example:" -ForegroundColor Yellow
    foreach ($m in $missing) { Write-Host "    - $($m.Key)" -ForegroundColor Yellow }
    Write-Host "    Fix:  .\scripts\sync-env.ps1   (adds them with .env.example defaults/placeholders)" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $envPath)) { New-Item -ItemType File -Path $envPath | Out-Null }

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
$block = @("", "# --- synced from .env.example on $stamp (replace any placeholder secrets) ---")
$block += ($missing | ForEach-Object { $_.Line })
# ASCII keeps it BOM-free and byte-compatible with the existing file.
Add-Content -LiteralPath $envPath -Value $block -Encoding ascii

Write-Host "[env-sync] Added $($missing.Count) key(s) to .env:" -ForegroundColor Green
foreach ($m in $missing) { Write-Host "    + $($m.Key)" -ForegroundColor Green }
Write-Host "Review .env and set real values for any placeholders (e.g. BE_JWT_SECRET, *_SUPABASE_*)." -ForegroundColor DarkGray
exit 0
