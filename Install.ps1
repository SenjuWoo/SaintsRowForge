# Saints Row Forge - installer. No admin required.
# Installs the forge core to %LOCALAPPDATA%\SaintsRowForge and verifies it.
#
# The install is staged and activated, not mirrored in place: the previous code is moved aside
# first, and it comes back if activation or the doctor fails. Workspaces, Inbox, logs and the
# imported-tool vault are never part of the swap, so user data survives every path.
#
#   .\Install.ps1                                   # normal install
#   .\Install.ps1 -Source <checkout> -Target <dir>  # used by tests\Test-Installer.ps1
param(
    [string]$Source = $PSScriptRoot,
    [string]$Target
)
$ErrorActionPreference = "Stop"

$src = if ($Source) { $Source } else { (Get-Location).Path }
$dst = if ($Target) { $Target } else { Join-Path $env:LOCALAPPDATA "SaintsRowForge" }
$root = Split-Path -Parent $dst

# Code that is replaced wholesale. START-HERE.bat is code, not data.
$coreItems = @("src", "mcp_server", "tests", "knowledge", "scripts",
               "README.md", "AI-INTEGRATION.md", "THIRD-PARTY-NOTICES.md", "START-HERE.bat")
# Directories that belong to the user and are never mirrored over.
$dataDirs = @("Workspaces", "Inbox", "logs", "tools_vault")

Write-Host "== Saints Row Forge install =="
Write-Host "source: $src"
Write-Host "target: $dst"

function Remove-Stale {
    # A killed run leaves a stage/backup folder behind; keep the newest, drop the rest.
    Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^SaintsRowForge\.(stage|backup)-' -and
                       $_.LastWriteTime -lt (Get-Date).AddDays(-1) } |
        ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }
}

function Copy-Core([string]$From, [string]$Into) {
    foreach ($item in $coreItems) {
        $source = Join-Path $From $item
        if (-not (Test-Path $source)) { continue }
        if ((Get-Item $source).PSIsContainer) {
            robocopy $source (Join-Path $Into $item) /MIR /NFL /NDL /NJH /NJS | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "robocopy failed on $item (exit $LASTEXITCODE)" }
        } else {
            Copy-Item -Force $source (Join-Path $Into $item)
        }
    }
}

function Restore-Code([string]$Backup, [string]$Live, [string[]]$Items) {
    foreach ($item in $Items) {
        $old = Join-Path $Backup $item
        if (-not (Test-Path $old)) { continue }
        $current = Join-Path $Live $item
        if (Test-Path $current) { Remove-Item -Recurse -Force $current }
        Move-Item -Force $old $current
    }
}

Remove-Stale

# 1. stage the new code next to the target, so activation is a rename on one volume
$stage = Join-Path $root ("SaintsRowForge.stage-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
    Copy-Core -From $src -Into $stage
} catch {
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    Write-Error "Install failed while staging: $_"
    exit 1
}

# 2. activate: move the old code aside, move the staged code in, and keep the two-in-one transaction
New-Item -ItemType Directory -Force -Path $dst | Out-Null
foreach ($d in $dataDirs) { New-Item -ItemType Directory -Force -Path (Join-Path $dst $d) | Out-Null }

$backup = Join-Path $root ("SaintsRowForge.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $backup | Out-Null
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
    Restore-Code -Backup $backup -Live $dst -Items $moved
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    Write-Error ("Install failed while activating: {0}. Previous code restored from {1}" -f $_, $backup)
    exit 1
}

# 3. verify with the owner's own doctor; a failure means this install is not ready, not "done"
Write-Host ""
& python (Join-Path $dst "src\srforge_cli.py") doctor
$healthy = ($LASTEXITCODE -eq 0)
if (-not $healthy) {
    Restore-Code -Backup $backup -Live $dst -Items @($coreItems)
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Warning "doctor reported problems: this build is not ready, so the previous code was restored."
    Write-Host "Previous code is still in $backup if you need it."
    exit 1
}
Remove-Item -Recurse -Force $stage, $backup -ErrorAction SilentlyContinue

# third-party tools stay OUT of the repo/installer: import them instead
Write-Host ""
Write-Host "Third-party tools (ThomasJepp, SRIV SDK) are NOT bundled."
Write-Host "Drop downloads into: $dst\Inbox   then run:"
Write-Host "    python src\srforge_cli.py deps import"
Write-Host ""
Write-Host "Done. Double-click START-HERE.bat, or wire the MCP server:"
Write-Host "    python $dst\mcp_server\server.py"
