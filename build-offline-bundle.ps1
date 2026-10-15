<#
.SYNOPSIS
    Build a fully self-contained offline install bundle for Local CLE.

.DESCRIPTION
    Runs on an INTERNET-connected Windows machine. Collects everything needed to
    install CLE on a machine with no internet:
      - OS installers (Python, Git, Ollama)
      - Python wheels (pip download of the project's dependencies + build backend)
      - Ollama models (manifest + referenced blobs, copied from the local store)
      - CLE source + config + the offline installer (setup.ps1 / verify.ps1)
      - manifest.json + checksums/SHA256SUMS.txt

    Idempotent: existing valid artifacts are reused. Prints a size summary.

.PARAMETER OutputRoot
    Where to create the bundle directory. Default: <repo>\dist (git-ignored).

.PARAMETER Models
    Optional 'role=model' overrides, e.g. -Models fast=llama3.2,coding=qwen2.5-coder:7b.
    Without this, roles come from .cle\config.yaml (if present) else the built-in
    recommended defaults. Only models present in the local Ollama store are packaged.

.PARAMETER SkipInstallers
    Do not download the Python/Git/Ollama installers.

.PARAMETER SkipModels
    Do not package any models.

.PARAMETER Force
    Re-download/re-copy artifacts even if present.

.PARAMETER PythonInstallerUrl / GitInstallerUrl / OllamaInstallerUrl
    Override the default installer download URLs.

.EXAMPLE
    .\build-offline-bundle.ps1
.EXAMPLE
    .\build-offline-bundle.ps1 -Models fast=llama3.2,embedding=nomic-embed-text -SkipInstallers
#>
[CmdletBinding()]
param(
    [string]$OutputRoot,
    [string[]]$Models,
    [switch]$SkipInstallers,
    [switch]$SkipModels,
    [switch]$Force,
    [string]$PythonInstallerUrl,
    [string]$GitInstallerUrl,
    [string]$OllamaInstallerUrl,
    [switch]$Help
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
Import-Module (Join-Path $RepoRoot 'scripts\CleSetup.psm1') -Force

if ($Help) {
    Write-Host 'build-offline-bundle.ps1 - see the header for options (-OutputRoot, -Models, -SkipInstallers, -SkipModels, -Force).'
    exit 0
}

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

# Version resolution lives in CleSetup.psm1 (Get-CleVersion), so it is unit-tested
# and single-sourced from cle/__init__.py (pyproject uses a dynamic version).

function Get-CleConfigRoleModels {
    param([string]$Repo)
    $result = [ordered]@{}
    $cfg = Join-Path $Repo '.cle\config.yaml'
    if (-not (Test-Path -LiteralPath $cfg)) { return $result }
    $inModels = $false
    foreach ($line in (Get-Content -LiteralPath $cfg)) {
        if ($line -match '^\s*models:\s*$') { $inModels = $true; continue }
        if ($inModels) {
            if ($line -match '^\S') { break }
            if ($line -match '^\s+(?<role>\w+):\s*"?(?<model>[^"#]*?)"?\s*(#.*)?$') {
                $v = $Matches['model'].Trim()
                if ($v) { $result[$Matches['role']] = $v }
            }
        }
    }
    return $result
}

function Copy-CleSourceTree {
    param([string]$Repo, [string]$Dest)
    $exclude = @('.git', '.venv', 'dist', 'logs', '.cle', '__pycache__',
        '.pytest_cache', '.mypy_cache', '.ruff_cache')
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Get-ChildItem -LiteralPath $Repo -Force | ForEach-Object {
        if ($exclude -contains $_.Name) { return }
        $target = Join-Path $Dest $_.Name
        # Clean overwrite: remove an existing target first so re-runs don't nest
        # directories (Copy-Item -Recurse onto an existing dir creates dir\dir).
        if (Test-Path -LiteralPath $target) { Remove-Item -Recurse -Force -LiteralPath $target }
        Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force
    }
    # Prune caches that slipped through.
    Get-ChildItem -LiteralPath $Dest -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @('__pycache__', '.pytest_cache') } |
        ForEach-Object { Remove-Item -Recurse -Force -LiteralPath $_.FullName -ErrorAction SilentlyContinue }
}

function Save-CleDownload {
    param([string]$Url, [string]$Dest, [string]$Label)
    if ((Test-Path -LiteralPath $Dest) -and -not $Force -and (Get-Item $Dest).Length -gt 0) {
        Write-CleLog "$Label already downloaded ($(Format-CleSize (Get-Item $Dest).Length))" -Level OK
        return $true
    }
    Write-CleLog "Downloading $Label ..." -Level INFO
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing -ErrorAction Stop
        Write-CleLog "$Label -> $(Format-CleSize (Get-Item $Dest).Length)" -Level OK
        return $true
    }
    catch {
        Write-CleLog "Failed to download $Label from $Url : $($_.Exception.Message)" -Level WARN
        if (Test-Path -LiteralPath $Dest) { Remove-Item -LiteralPath $Dest -Force -ErrorAction SilentlyContinue }
        return $false
    }
}

# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------

$cleVersion = Get-CleVersion -Repo $RepoRoot
$bundleName = "CLE-OFFLINE-BUNDLE-$cleVersion"
if (-not $OutputRoot) { $OutputRoot = Join-Path $RepoRoot 'dist' }
$Bundle = Join-Path $OutputRoot $bundleName

$logDir = Join-Path $RepoRoot 'logs'
[void](Initialize-CleLog -Path (Join-Path $logDir ('build-' + (Get-Date).ToString('yyyyMMdd-HHmmss') + '.log')))

Write-Host ''
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host '        CLE OFFLINE BUNDLE BUILDER' -ForegroundColor Cyan
Write-Host ("        CLE $cleVersion  ->  $bundleName") -ForegroundColor Cyan
Write-Host '==================================================' -ForegroundColor Cyan

$py = Get-ClePython -Minimum ([version]'3.11')
if (-not $py) {
    Write-CleLog 'No Python 3.11+ found; needed to download wheels (pip download).' -Level ERROR
    exit 1
}
$pyVersion = $py.Version.ToString()
Write-CleLog "Builder Python: $pyVersion ($($py.Exe) $($py.LauncherArgs -join ' '))" -Level OK

# Resolve role -> model map.
$roleMap = [ordered]@{}
$rec = Get-CleRecommendedModels
foreach ($role in $rec.Keys) { $roleMap[$role] = $rec[$role] }
$cfgRoles = Get-CleConfigRoleModels -Repo $RepoRoot
foreach ($role in $cfgRoles.Keys) { $roleMap[$role] = $cfgRoles[$role] }
if ($Models) {
    foreach ($pair in $Models) {
        $kv = $pair -split '=', 2
        if ($kv.Count -eq 2 -and $kv[0].Trim()) { $roleMap[$kv[0].Trim()] = $kv[1].Trim() }
    }
}

# --------------------------------------------------------------------------
# Bundle skeleton
# --------------------------------------------------------------------------

Write-CleLog 'Preparing bundle directory' -Level STEP
foreach ($d in @('', 'installers\python', 'installers\git', 'installers\ollama',
        'packages', 'models\manifests', 'models\blobs', 'checksums', 'docs', 'logs')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Bundle $d) | Out-Null
}

# --------------------------------------------------------------------------
# CLE source + offline installer
# --------------------------------------------------------------------------

Write-CleLog 'Copying CLE source and installer' -Level STEP
Copy-CleSourceTree -Repo $RepoRoot -Dest $Bundle
Write-CleLog 'CLE source copied (cle/, configs/, tests/, setup.ps1, verify.ps1, scripts/, docs/)' -Level OK

# --------------------------------------------------------------------------
# Installers
# --------------------------------------------------------------------------

$installerInfo = @{ python = $null; git = $null; ollama = $null }
if (-not $SkipInstallers) {
    Write-CleLog 'Downloading OS installers' -Level STEP
    if (-not $PythonInstallerUrl) {
        $PythonInstallerUrl = "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-amd64.exe"
    }
    if (-not $GitInstallerUrl) {
        $GitInstallerUrl = 'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe'
    }
    if (-not $OllamaInstallerUrl) {
        $OllamaInstallerUrl = 'https://ollama.com/download/OllamaSetup.exe'
    }
    $pyExe = Join-Path $Bundle ("installers\python\" + (Split-Path -Leaf $PythonInstallerUrl))
    $gitExe = Join-Path $Bundle ("installers\git\" + (Split-Path -Leaf $GitInstallerUrl))
    $olExe = Join-Path $Bundle 'installers\ollama\OllamaSetup.exe'
    if (Save-CleDownload -Url $PythonInstallerUrl -Dest $pyExe -Label 'Python installer') { $installerInfo.python = (Split-Path -Leaf $pyExe) }
    if (Save-CleDownload -Url $GitInstallerUrl -Dest $gitExe -Label 'Git installer') { $installerInfo.git = (Split-Path -Leaf $gitExe) }
    if (Save-CleDownload -Url $OllamaInstallerUrl -Dest $olExe -Label 'Ollama installer') { $installerInfo.ollama = (Split-Path -Leaf $olExe) }
}
else {
    Write-CleLog 'Skipping installers (-SkipInstallers)' -Level WARN
}

# --------------------------------------------------------------------------
# Python wheels
# --------------------------------------------------------------------------

Write-CleLog 'Downloading Python packages (pip download)' -Level STEP
$pkgDir = Join-Path $Bundle 'packages'
$dlOk = $true
# The build backend + a bootstrap pip, so an offline venv can build the -e project.
$builderPy = $py.Exe
$builderArgs = @()
if ($py.LauncherArgs.Count -gt 0) { $builderArgs += $py.LauncherArgs }

Write-CleLog 'Resolving + downloading dependency wheels ...' -Level INFO
& $builderPy @builderArgs -m pip download --dest $pkgDir --prefer-binary pip setuptools wheel | Out-Host
if ($LASTEXITCODE -ne 0) { $dlOk = $false }
& $builderPy @builderArgs -m pip download --dest $pkgDir --prefer-binary "$RepoRoot[dev]" | Out-Host
if ($LASTEXITCODE -ne 0) { $dlOk = $false }

$wheels = @(Get-ChildItem -LiteralPath $pkgDir -File -ErrorAction SilentlyContinue)
if ($dlOk) {
    Write-CleLog "Downloaded $($wheels.Count) package file(s)" -Level OK
}
else {
    Write-CleLog "pip download reported an error; packages may be incomplete ($($wheels.Count) files)" -Level WARN
}

# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

$modelsIndex = @()
$storeDir = Get-CleOllamaModelsDir
$copiedBlobs = @{}
if (-not $SkipModels) {
    Write-CleLog 'Packaging Ollama models (manifest + blobs)' -Level STEP
    Write-CleLog "Ollama store: $storeDir" -Level DEBUG
    foreach ($role in $roleMap.Keys) {
        $model = $roleMap[$role]
        $ref = Resolve-CleModelRef -Model $model
        $mf = Find-CleOllamaManifest -ModelsDir $storeDir -Name $ref.Name -Tag $ref.Tag
        if (-not $mf) {
            Write-CleLog "Model for role '$role' not in local store: $model (skipped)" -Level WARN
            continue
        }
        $digests = Get-CleManifestDigests -ManifestPath $mf
        $sizeBytes = 0
        foreach ($dg in $digests) {
            $blobName = ConvertTo-CleBlobFileName -Digest $dg
            $src = Join-Path $storeDir ("blobs\" + $blobName)
            if (-not (Test-Path -LiteralPath $src)) {
                Write-CleLog "Missing blob $blobName for $model" -Level WARN
                continue
            }
            $sizeBytes += (Get-Item $src).Length
            if (-not $copiedBlobs.ContainsKey($blobName)) {
                $dst = Join-Path $Bundle ("models\blobs\" + $blobName)
                if ($Force -or -not (Test-Path -LiteralPath $dst)) {
                    Copy-Item -LiteralPath $src -Destination $dst -Force
                }
                $copiedBlobs[$blobName] = $true
            }
        }
        # Copy the manifest preserving its path under manifests/.
        $relManifest = $mf.Substring((Join-Path $storeDir 'manifests').Length).TrimStart('\', '/')
        $dstManifest = Join-Path (Join-Path $Bundle 'models\manifests') $relManifest
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dstManifest) | Out-Null
        Copy-Item -LiteralPath $mf -Destination $dstManifest -Force
        $modelsIndex += [pscustomobject]@{
            role         = $role
            model        = $model
            name         = $ref.Name
            tag          = $ref.Tag
            manifestRel  = ('models/manifests/' + ($relManifest -replace '\\', '/'))
            digests      = $digests
            sizeBytes    = $sizeBytes
        }
        Write-CleLog "Packaged $model ($role) - $(Format-CleSize $sizeBytes)" -Level OK
    }
    $modelsIndex | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Bundle 'models\models-index.json') -Encoding UTF8
}
else {
    Write-CleLog 'Skipping models (-SkipModels)' -Level WARN
}

# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

Write-CleLog 'Writing manifest.json' -Level STEP
$pkgList = @()
foreach ($w in $wheels) { $pkgList += $w.Name }
$manifest = [ordered]@{
    bundle_version = $cleVersion
    cle_version    = $cleVersion
    built_at       = (Get-Date).ToString('s')
    platform       = 'windows-amd64'
    python         = [ordered]@{ version = $pyVersion; installer = $installerInfo.python }
    git            = [ordered]@{ installer = $installerInfo.git }
    ollama         = [ordered]@{ source_version = (Invoke-CleCapture -Exe 'ollama' -Arguments @('--version')).Trim(); installer = $installerInfo.ollama }
    python_packages = $pkgList
    models         = $modelsIndex
    checksums_file = 'checksums/SHA256SUMS.txt'
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Bundle 'manifest.json') -Encoding UTF8

# --------------------------------------------------------------------------
# README-OFFLINE
# --------------------------------------------------------------------------

@"
LOCAL CLE - OFFLINE INSTALL BUNDLE ($bundleName)

This directory installs Local CLE on a Windows machine with NO internet.

1. Copy this whole folder to the offline machine (USB / external drive).
2. Open PowerShell in this folder.
3. (Optional) Verify the bundle:   .\verify.ps1
4. Install:                        .\setup.ps1 -Offline
   (or, if PowerShell blocks scripts:  setup.cmd -Offline)

No internet is required or contacted in offline mode.

Contents:
  installers\   Python, Git, Ollama installers
  packages\     Python wheels (installed with pip --no-index)
  models\       Ollama models (manifest + blobs, imported into the model store)
  cle\, configs\, tests\, pyproject.toml   CLE source
  manifest.json, checksums\SHA256SUMS.txt  bundle description + integrity

See docs\OFFLINE-INSTALLATION.md for details and troubleshooting.
"@ | Set-Content -LiteralPath (Join-Path $Bundle 'README-OFFLINE.txt') -Encoding UTF8

# --------------------------------------------------------------------------
# Checksums
# --------------------------------------------------------------------------

Write-CleLog 'Generating checksums (SHA256SUMS.txt)' -Level STEP
$sumsPath = Join-Path $Bundle 'checksums\SHA256SUMS.txt'
$lines = New-Object System.Collections.ArrayList
# Exclude the checksums file itself and any runtime/install artifacts that an
# in-place install may have created inside the bundle (.venv, .cle, logs,
# caches) so the manifest covers only distributable artifacts.
$excludeSegments = @('\.venv\', '\.cle\', '\logs\', '\__pycache__\', '\.pytest_cache\')
$allFiles = Get-ChildItem -LiteralPath $Bundle -Recurse -File | Where-Object {
    if ($_.FullName -eq $sumsPath) { return $false }
    foreach ($seg in $excludeSegments) { if ($_.FullName -like "*$seg*") { return $false } }
    return $true
}
foreach ($f in $allFiles) {
    $rel = $f.FullName.Substring($Bundle.Length).TrimStart('\', '/') -replace '\\', '/'
    $hash = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLower()
    [void]$lines.Add("$hash *$rel")
}
$lines | Set-Content -LiteralPath $sumsPath -Encoding ASCII
Write-CleLog "Checksums written for $($allFiles.Count) file(s)" -Level OK

# --------------------------------------------------------------------------
# Size summary
# --------------------------------------------------------------------------

function Get-DirSize {
    param([string]$P)
    if (-not (Test-Path -LiteralPath $P)) { return 0 }
    $files = @(Get-ChildItem -LiteralPath $P -Recurse -File -ErrorAction SilentlyContinue)
    if ($files.Count -eq 0) { return 0 }
    $m = $files | Measure-Object -Property Length -Sum
    if ($m -and $m.Sum) { return [double]$m.Sum }
    return 0
}
$szInstallers = Get-DirSize (Join-Path $Bundle 'installers')
$szPackages = Get-DirSize (Join-Path $Bundle 'packages')
$szModels = Get-DirSize (Join-Path $Bundle 'models')
$szTotal = Get-DirSize $Bundle

Write-Host ''
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host '        BUNDLE BUILD COMPLETE' -ForegroundColor Cyan
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host ("  Location:   {0}" -f $Bundle)
Write-Host ("  Installers: {0}" -f (Format-CleSize $szInstallers))
Write-Host ("  Packages:   {0} ({1} files)" -f (Format-CleSize $szPackages), $wheels.Count)
Write-Host ("  Models:     {0} ({1} model(s), {2} blob(s))" -f (Format-CleSize $szModels), $modelsIndex.Count, $copiedBlobs.Count)
Write-Host ("  TOTAL:      {0}" -f (Format-CleSize $szTotal)) -ForegroundColor Green
if ($modelsIndex.Count -gt 0) {
    Write-Host '  Models packaged:'
    foreach ($m in $modelsIndex) { Write-Host ("    {0,-10} {1,-24} {2}" -f $m.role, $m.model, (Format-CleSize $m.sizeBytes)) }
}
Write-Host '=================================================='
Write-Host ("  Verify with:  .\verify.ps1   (inside the bundle)")
Write-Host ("  Install with: .\setup.ps1 -Offline")
Write-Host '=================================================='
Write-Host ''
exit 0
