# Saints Row Forge - updater. Replaces code from a checkout, keeps every byte of user data.
#
# Same staging and rollback contract as Install.ps1: the new code lands in a stage folder, the old
# code moves to a backup folder, and a failed activation or a failing doctor restores the previous
# version instead of leaving a half-updated install behind.
#
#   .\Update.ps1                                   # update from this checkout
#   .\Update.ps1 -Source <checkout> -Target <dir>  # used by tests\Test-Installer.ps1
param(
    [string]$Source = $PSScriptRoot,
    [string]$Target
)
$ErrorActionPreference = "Stop"

$src = if ($Source) { $Source } else { (Get-Location).Path }
$dst = if ($Target) { $Target } else { Join-Path $env:LOCALAPPDATA "SaintsRowForge" }
$root = Split-Path -Parent $dst
$coreItems = @("src", "mcp_server", "tests", "knowledge", "scripts",
               "README.md", "AI-INTEGRATION.md", "THIRD-PARTY-NOTICES.md", "START-HERE.bat")

if (-not (Test-Path (Join-Path $dst "src\srforge_cli.py"))) {
    Write-Error "Not installed. Run Install.ps1 first."
    exit 1
}

$stage = Join-Path $root ("SaintsRowForge.stage-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$backup = Join-Path $root ("SaintsRowForge.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $stage, $backup | Out-Null

function Restore-Code([string]$From, [string]$Live, [string[]]$Items) {
    foreach ($item in $Items) {
        $old = Join-Path $From $item
        if (-not (Test-Path $old)) { continue }
        $current = Join-Path $Live $item
        if (Test-Path $current) { Remove-Item -Recurse -Force $current }
        Move-Item -Force $old $current
    }
}

try {
    foreach ($item in $coreItems) {
        $from = Join-Path $src $item
        if (-not (Test-Path $from)) { continue }
        if ((Get-Item $from).PSIsContainer) {
            robocopy $from (Join-Path $stage $item) /MIR /NFL /NDL /NJH /NJS | Out-Null
        } else {
            Copy-Item -Force $from (Join-Path $stage $item)
        }
        if ($LASTEXITCODE -ge 8) { throw "robocopy failed on $item (exit $LASTEXITCODE)" }
    }
} catch {
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    Write-Error "Update failed while staging: $_"
    exit 1
}

$moved = @()
try {
    foreach ($item in $coreItems) {
        $live = Join-Path $dst $item
        if (Test-Path $live) {
            Move-Item -Force $live (Join-Path $backup $item)
            $moved += $item
        }
    }
    foreach ($item in $coreItems) {
        $staged = Join-Path $stage $item
        if (Test-Path $staged) { Move-Item -Force $staged (Join-Path $dst $item) }
    }
} catch {
    Restore-Code -From $backup -Live $dst -Items $moved
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    Write-Error ("Update failed while activating: {0}. Previous code restored." -f $_)
    exit 1
}

& python (Join-Path $dst "src\srforge_cli.py") doctor
if ($LASTEXITCODE -ne 0) {
    Restore-Code -From $backup -Live $dst -Items $coreItems
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    Write-Warning "doctor reported problems: update rolled back to the previous version ($backup)."
    exit 1
}

Remove-Item -Recurse -Force $stage, $backup -ErrorAction SilentlyContinue
Write-Host "Updated code at $dst (Workspaces/Inbox/logs/tools_vault untouched)."
