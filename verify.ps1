<#
.SYNOPSIS
    Verify a CLE offline bundle's integrity without installing anything.

.DESCRIPTION
    Run from inside a bundle directory. Checks the manifest, SHA256 checksums of
    every listed file, and the presence of installers, Python packages, and model
    artifacts (manifest + all referenced blobs). Makes no changes.

    Exit code 0 = valid; 1 = invalid (missing/mismatched artifacts).

.EXAMPLE
    .\verify.ps1
#>
[CmdletBinding()]
param([switch]$Help)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

if ($Help) { Write-Host 'verify.ps1 - validate a CLE offline bundle (no changes). Exit 1 if invalid.'; exit 0 }

$Bundle = $PSScriptRoot
$module = Join-Path $Bundle 'scripts\CleSetup.psm1'
if (-not (Test-Path -LiteralPath $module)) {
    Write-Host "FATAL: scripts\CleSetup.psm1 not found; run verify.ps1 from inside the bundle." -ForegroundColor Red
    exit 2
}
Import-Module $module -Force

$errors = New-Object System.Collections.ArrayList
$warns = New-Object System.Collections.ArrayList
function Fail($m) { [void]$errors.Add($m); Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Warn($m) { [void]$warns.Add($m); Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Ok($m) { Write-Host "  [OK]   $m" -ForegroundColor Green }

Write-Host ''
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host '        CLE OFFLINE BUNDLE - VERIFY' -ForegroundColor Cyan
Write-Host '==================================================' -ForegroundColor Cyan

# 1. manifest
$manifestPath = Join-Path $Bundle 'manifest.json'
$manifest = $null
if (Test-Path -LiteralPath $manifestPath) {
    try { $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json; Ok "manifest.json (CLE $($manifest.cle_version))" }
    catch { Fail "manifest.json is not valid JSON: $($_.Exception.Message)" }
}
else { Fail 'manifest.json is missing' }

# 2. checksums
$sumsPath = Join-Path $Bundle 'checksums\SHA256SUMS.txt'
$sums = @{}
if (Test-Path -LiteralPath $sumsPath) {
    $sums = Read-CleSha256Sums -Path $sumsPath
    Ok "checksums/SHA256SUMS.txt ($($sums.Count) entries)"
}
else { Fail 'checksums/SHA256SUMS.txt is missing' }

# 3. verify every checksummed file
$checked = 0; $mismatch = 0; $missing = 0
foreach ($rel in $sums.Keys) {
    $full = Join-Path $Bundle ($rel -replace '/', '\')
    if (-not (Test-Path -LiteralPath $full)) { $missing++; Fail "missing file: $rel"; continue }
    $actual = Get-CleFileSha256 -Path $full
    if ($actual -ne $sums[$rel]) { $mismatch++; Fail "checksum mismatch: $rel" }
    $checked++
}
if ($sums.Count -gt 0 -and $mismatch -eq 0 -and $missing -eq 0) {
    Ok "checksum verification: $checked file(s) OK"
}

# 4. installers (informational: a machine may already have the tool)
if ($manifest) {
    foreach ($tool in @('python', 'git', 'ollama')) {
        $inst = $manifest.$tool.installer
        if ($inst) {
            $p = Get-ChildItem -LiteralPath (Join-Path $Bundle "installers\$tool") -File -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($p) { Ok "installer ($tool): $($p.Name)" } else { Warn "installer ($tool) listed in manifest but not found" }
        }
        else { Warn "no $tool installer bundled (offline machine must already have $tool)" }
    }
}

# 5. packages
$pkgs = @(Get-ChildItem -LiteralPath (Join-Path $Bundle 'packages') -File -ErrorAction SilentlyContinue)
if ($pkgs.Count -gt 0) { Ok "python packages: $($pkgs.Count) file(s)" } else { Fail 'no Python packages in packages\' }

# 6. models
if ($manifest -and $manifest.models) {
    foreach ($m in $manifest.models) {
        $mfFull = Join-Path $Bundle ($m.manifestRel -replace '/', '\')
        if (-not (Test-Path -LiteralPath $mfFull)) { Fail "model '$($m.model)' ($($m.role)): manifest missing"; continue }
        $blobMissing = 0
        foreach ($dg in $m.digests) {
            $blob = Join-Path $Bundle ('models\blobs\' + (ConvertTo-CleBlobFileName -Digest $dg))
            if (-not (Test-Path -LiteralPath $blob)) { $blobMissing++ }
        }
        if ($blobMissing -gt 0) { Fail "model '$($m.model)' ($($m.role)): $blobMissing blob(s) missing" }
        else { Ok "model '$($m.model)' ($($m.role)): manifest + $($m.digests.Count) blob(s)" }
    }
}
elseif ($manifest) { Warn 'no models packaged in this bundle' }

# Summary
Write-Host '--------------------------------------------------'
if ($errors.Count -eq 0) {
    Write-Host ("  Bundle is valid ({0} warning(s))." -f $warns.Count) -ForegroundColor Green
    Write-Host '  Install with:  .\setup.ps1 -Offline'
    Write-Host '=================================================='
    exit 0
}
Write-Host ("  Bundle is INVALID: {0} error(s), {1} warning(s)." -f $errors.Count, $warns.Count) -ForegroundColor Red
Write-Host '  Rebuild it on an online machine:  .\build-offline-bundle.ps1'
Write-Host '=================================================='
exit 1
