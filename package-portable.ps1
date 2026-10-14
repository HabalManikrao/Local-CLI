<#
.SYNOPSIS
    Assemble a single self-contained folder with everything needed to install
    Local CLE on a new machine. Copy that folder, then double-click install.cmd.

.DESCRIPTION
    Produces <OutDir> (default: dist\CLE-Install) containing only the files the
    installer needs at runtime — the two installers, the setup helper module, the
    Python package, its config and build metadata — with build/venv/git/test
    artifacts stripped out. Re-run after changing the code to refresh it.

.PARAMETER Zip
    Also produce <OutDir>.zip (spec-compliant, forward-slash entries) next to it.

.EXAMPLE
    .\package-portable.ps1
.EXAMPLE
    .\package-portable.ps1 -Zip
.EXAMPLE
    .\package-portable.ps1 -OutDir D:\USB\CLE-Install
#>
[CmdletBinding()]
param([string]$OutDir, [switch]$Zip)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $root 'dist\CLE-Install' }

Write-Host "Assembling portable install folder -> $OutDir" -ForegroundColor Cyan
if (Test-Path -LiteralPath $OutDir) { Remove-Item -LiteralPath $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# Top-level files the installer + build need on a fresh machine.
$files = @(
    'install.cmd',      # double-click entry point (self-elevates)
    'install.ps1',      # the installer
    'pyproject.toml',   # build metadata for `pip install -e .`
    'README.md',        # required by pyproject (readme=...) and handy on arrival
    'CHANGELOG.md'
)
foreach ($f in $files) {
    Copy-Item -LiteralPath (Join-Path $root $f) -Destination (Join-Path $OutDir $f) -Force
}

# Directories (recursive). cle/ is the package; scripts/ holds the setup module;
# configs/ holds default.yaml; docs/ a couple of guides.
Copy-Item -LiteralPath (Join-Path $root 'scripts') -Destination (Join-Path $OutDir 'scripts') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $root 'configs') -Destination (Join-Path $OutDir 'configs') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $root 'cle')     -Destination (Join-Path $OutDir 'cle')     -Recurse -Force

New-Item -ItemType Directory -Path (Join-Path $OutDir 'docs') -Force | Out-Null
foreach ($d in @('USAGE.md', 'RUNNING-LOCALLY.md', 'TROUBLESHOOTING.md')) {
    $src = Join-Path $root "docs\$d"
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination (Join-Path $OutDir "docs\$d") -Force }
}

# Strip caches that may have been copied from cle/.
Get-ChildItem -LiteralPath $OutDir -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

# Report.
$count = (Get-ChildItem -LiteralPath $OutDir -Recurse -File).Count
$bytes = (Get-ChildItem -LiteralPath $OutDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
$mb = [math]::Round($bytes / 1MB, 2)
Write-Host ("Done: {0} files, {1} MB" -f $count, $mb) -ForegroundColor Green

if ($Zip) {
    $zipPath = "$OutDir.zip"
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    # Zips the folder itself so it extracts to a single CLE-Install\ folder.
    Compress-Archive -Path $OutDir -DestinationPath $zipPath -CompressionLevel Optimal
    $zmb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 2)
    Write-Host ("Zipped: {0} ({1} MB)" -f $zipPath, $zmb) -ForegroundColor Green
}

Write-Host ""
Write-Host "Copy this folder (or the .zip) to the new machine, then double-click install.cmd inside it." -ForegroundColor Cyan
Write-Host $OutDir
