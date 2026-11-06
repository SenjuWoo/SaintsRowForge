# Installer/updater contract tests. No network, no admin, no writes outside a temp folder.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-Installer.ps1
#
# Covers: fresh install, user data preserved by an update, a failing doctor rolling back to the
# previous code, and no stage/backup litter left behind on success.
[CmdletBinding()]
param([string]$RepoRoot)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$failures = 0

function Check([string]$Name, [scriptblock]$Body) {
    try { & $Body; Write-Host "ok   $Name" }
    catch { $script:failures++; Write-Host "FAIL $Name -> $_" }
}

function New-FakeSource([string]$Path, [int]$DoctorExit) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Path "src") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $Path "mcp_server") | Out-Null
    Set-Content -Path (Join-Path $Path "src\srforge_cli.py") -Encoding ASCII -Value @"
import sys
print('doctor placeholder')
sys.exit($DoctorExit)
"@
    Set-Content -Path (Join-Path $Path "mcp_server\server.py") -Encoding ASCII -Value "# placeholder"
    Set-Content -Path (Join-Path $Path "START-HERE.bat") -Encoding ASCII -Value "@echo off"
    Set-Content -Path (Join-Path $Path "README.md") -Encoding ASCII -Value "# fake"
}

function Invoke-Script([string]$Script, [string]$Source, [string]$Target) {
    # A child script's stderr arrives as error records; keep them as text so a deliberate
    # non-zero exit is measured instead of thrown.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Source $Source -Target $Target 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    return @{ code = $code; output = $out }
}

$sandbox = Join-Path ([IO.Path]::GetTempPath()) ("srforge-installer-" + [guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Force -Path $sandbox | Out-Null

    Check "fresh install stages, activates and leaves no litter" {
        $src = Join-Path $sandbox "good"; New-FakeSource $src 0
        $dst = Join-Path $sandbox "live"
        $r = Invoke-Script (Join-Path $RepoRoot "Install.ps1") $src $dst
        if ($r.code -ne 0) { throw "installer exited $($r.code)`n$($r.output)" }
        if (-not (Test-Path (Join-Path $dst "src\srforge_cli.py"))) { throw "code missing after install" }
        foreach ($d in @("Workspaces", "Inbox", "logs")) {
            if (-not (Test-Path (Join-Path $dst $d))) { throw "data dir $d missing" }
        }
        $litter = Get-ChildItem $sandbox -Directory | Where-Object { $_.Name -match '\.(stage|backup)-' }
        if ($litter) { throw "leftover: $($litter.Name -join ', ')" }
    }

    Check "an update replaces code but keeps user data" {
        $src = Join-Path $sandbox "good2"; New-FakeSource $src 0
        Set-Content -Path (Join-Path $src "src\marker.txt") -Encoding ASCII -Value "v2"
        $dst = Join-Path $sandbox "live"
        Set-Content -Path (Join-Path $dst "Workspaces\keepme.txt") -Encoding ASCII -Value "user data"
        $r = Invoke-Script (Join-Path $RepoRoot "Update.ps1") $src $dst
        if ($r.code -ne 0) { throw "updater exited $($r.code)`n$($r.output)" }
        if (-not (Test-Path (Join-Path $dst "src\marker.txt"))) { throw "new code not active" }
        if (-not (Test-Path (Join-Path $dst "Workspaces\keepme.txt"))) { throw "user data was destroyed" }
    }

    Check "a failing doctor rolls back to the previous code and exits non-zero" {
        $good = Join-Path $sandbox "good3"; New-FakeSource $good 0
        Set-Content -Path (Join-Path $good "src\marker.txt") -Encoding ASCII -Value "v2"
        $dst = Join-Path $sandbox "live"
        $broken = Join-Path $sandbox "broken"; New-FakeSource $broken 1
        Set-Content -Path (Join-Path $broken "src\broken.txt") -Encoding ASCII -Value "boom"
        $r = Invoke-Script (Join-Path $RepoRoot "Update.ps1") $broken $dst
        if ($r.code -eq 0) { throw "a failing doctor was reported as success" }
        if (Test-Path (Join-Path $dst "src\broken.txt")) { throw "broken code stayed active" }
        if (-not (Test-Path (Join-Path $dst "src\marker.txt"))) { throw "previous code was not restored" }
        if (-not (Test-Path (Join-Path $dst "Workspaces\keepme.txt"))) { throw "user data was destroyed" }
    }

    Check "the updater refuses a machine with no install" {
        $src = Join-Path $sandbox "good4"; New-FakeSource $src 0
        $r = Invoke-Script (Join-Path $RepoRoot "Update.ps1") $src (Join-Path $sandbox "absent")
        if ($r.code -eq 0) { throw "updater claimed success without an install" }
    }
}
finally {
    Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failures) { Write-Host "$failures failed"; exit 1 }
Write-Host "all installer checks passed"
