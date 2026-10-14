<#
.SYNOPSIS
    Minimal installer for Local CLE. Installs prerequisites, pulls the required
    local models (skipping any already present), installs the package, and
    assigns model roles.

.DESCRIPTION
    A focused, single-purpose installer for a fresh Windows machine. It:
      1. Installs Python, Git, ripgrep and Ollama via winget (skips any already
         present).
      2. Creates the virtualenv and installs the `cle` package.
      3. Starts the Ollama daemon if it is not already running.
      4. Pulls the recommended models — but only the ones NOT already installed.
      5. Assigns each model to its task role.

    It is idempotent: re-running skips everything already in place. For the full
    experience (test suite, live smoke test, offline-bundle support) use
    setup.ps1 instead; this script is the lean "just get me running" path.

.PARAMETER SkipModels
    Install prerequisites and the package, but do not download or assign models.

.PARAMETER NonInteractive
    Do not prompt; assume "yes" for every install/download (unattended setup).

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -NonInteractive          # fully hands-off on a new machine
.EXAMPLE
    .\install.ps1 -SkipModels              # prerequisites + package only
#>
[CmdletBinding()]
param(
    [switch]$SkipModels,
    [switch]$NonInteractive
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
Import-Module (Join-Path $RepoRoot 'scripts\CleSetup.psm1') -Force

# Accumulate a small report so the end-of-run summary is scannable.
$script:Report = New-Object System.Collections.Generic.List[object]
function Add-Line {
    param([string]$Name, [string]$Status, [string]$Detail = '')
    $script:Report.Add([pscustomobject]@{ Name = $Name; Status = $Status; Detail = $Detail })
    $level = switch ($Status) { 'OK' { 'OK' } 'SKIP' { 'OK' } 'WARN' { 'WARN' } 'FAIL' { 'ERROR' } default { 'INFO' } }
    Write-CleLog ("{0,-22} {1}" -f $Name, $Detail) -Level $level
}

function Confirm-Yes {
    param([string]$Question)
    if ($NonInteractive) { return $true }
    $ans = Read-Host "$Question [Y/n]"
    return ([string]::IsNullOrWhiteSpace($ans) -or $ans -match '^(y|yes)$')
}

# --------------------------------------------------------------------------
# Ensure a single prerequisite (detect -> winget install if missing -> re-detect)
# --------------------------------------------------------------------------
function Install-Prereq {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Detect,  # returns a version string or $null
        [string]$WingetId,
        [bool]$Critical = $true
    )
    $found = & $Detect
    if (-not $found) { Update-CleProcessPath; $found = & $Detect }   # a prior install may have changed PATH
    if ($found) { Add-Line $Name 'OK' "present: $found"; return $true }

    if (-not $WingetId) { Add-Line $Name ($(if ($Critical) { 'FAIL' } else { 'WARN' })) 'missing; no auto-install'; return (-not $Critical) }
    if (-not (Confirm-Yes "Install $Name now?")) { Add-Line $Name ($(if ($Critical) { 'FAIL' } else { 'WARN' })) 'declined'; return (-not $Critical) }

    [void](Install-CleWingetPackage -Id $WingetId -Name $Name)
    Update-CleProcessPath
    $found = & $Detect
    if ($found) { Add-Line $Name 'OK' "installed: $found"; return $true }
    Add-Line $Name ($(if ($Critical) { 'FAIL' } else { 'WARN' })) 'still missing after install (open a NEW terminal and re-run)'
    return (-not $Critical)
}

Write-CleLog 'Local CLE installer' -Level STEP

# -- 1. Prerequisites -------------------------------------------------------
Write-CleLog 'Prerequisites' -Level STEP

$okPy = Install-Prereq -Name 'Python 3.11+' -WingetId 'Python.Python.3.12' -Critical $true -Detect {
    $p = Get-ClePython -Minimum ([version]'3.11'); if ($p) { "v$($p.Version)" } else { $null }
}
$okGit = Install-Prereq -Name 'Git' -WingetId 'Git.Git' -Critical $true -Detect {
    if (Test-CleCommand 'git') { (Invoke-CleCapture -Exe 'git' -Arguments @('--version')).Trim() } else { $null }
}
[void](Install-Prereq -Name 'ripgrep' -WingetId 'BurntSushi.ripgrep.MSVC' -Critical $false -Detect {
        if (Test-CleCommand 'rg') { (Invoke-CleCapture -Exe 'rg' -Arguments @('--version')).Split("`n")[0].Trim() } else { $null }
    })
$okOllama = Install-Prereq -Name 'Ollama' -WingetId 'Ollama.Ollama' -Critical $true -Detect {
    if (Test-CleCommand 'ollama') { (Invoke-CleCapture -Exe 'ollama' -Arguments @('--version')).Split("`n")[0].Trim() } else { $null }
}

if (-not ($okPy -and $okGit -and $okOllama)) {
    Write-CleLog 'A required prerequisite is missing. Resolve the items above and re-run.' -Level ERROR
    exit 1
}

# -- 2. Virtualenv + package ------------------------------------------------
Write-CleLog 'Package' -Level STEP
$venv = Join-Path $RepoRoot '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
$py = Get-ClePython -Minimum ([version]'3.11')
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-CleLog 'Creating virtualenv (.venv) ...' -Level INFO
    & $py.Exe @($py.LauncherArgs) -m venv $venv
}
Write-CleLog 'Installing the cle package (pip install -e .) ...' -Level INFO
& $venvPy -m pip install -q --upgrade pip | Out-Host
& $venvPy -m pip install -q -e (Join-Path $RepoRoot '.') | Out-Host
$cle = Join-Path $venv 'Scripts\cle.exe'
if (Test-Path -LiteralPath $cle) { Add-Line 'cle package' 'OK' 'installed into .venv' }
else { Add-Line 'cle package' 'FAIL' 'cle.exe not found after install'; exit 1 }

# -- 3. Ollama daemon -------------------------------------------------------
Write-CleLog 'Ollama daemon' -Level STEP
$hostUrl = Get-CleConfiguredHost -RepoRoot $RepoRoot
if (Test-CleOllamaApi -BaseUrl $hostUrl) {
    Add-Line 'Ollama daemon' 'OK' "reachable at $hostUrl"
}
else {
    Write-CleLog 'Starting the Ollama daemon ...' -Level INFO
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    if (Wait-CleOllamaApi -BaseUrl $hostUrl -TimeoutSec 60) { Add-Line 'Ollama daemon' 'OK' "started at $hostUrl" }
    else { Add-Line 'Ollama daemon' 'WARN' 'not reachable; model steps may be skipped' }
}
$daemonUp = Test-CleOllamaApi -BaseUrl $hostUrl

# -- 4. Models (download only the missing ones) -----------------------------
$recommended = Get-CleRecommendedModels
if ($SkipModels) {
    Add-Line 'Models' 'SKIP' '-SkipModels'
}
elseif (-not $daemonUp) {
    Add-Line 'Models' 'WARN' 'Ollama daemon unreachable; skipped'
}
else {
    Write-CleLog 'Models (download missing; skip already-present)' -Level STEP
    $installed = Get-CleModelNames -OllamaListOutput (Invoke-CleCapture -Exe 'ollama' -Arguments @('list'))
    foreach ($role in $recommended.Keys) {
        $model = $recommended[$role]
        if (Test-CleModelInstalled -Installed $installed -Model $model) {
            Add-Line "model:$role" 'SKIP' "$model already present"
            continue
        }
        $sz = Get-CleApproxModelSizeGB -Model $model
        $szTxt = if ($sz -gt 0) { " (~$sz GB)" } else { '' }
        if (-not (Confirm-Yes "Download $model for role '$role'$szTxt?")) {
            Add-Line "model:$role" 'SKIP' "declined ($model)"
            continue
        }
        Write-CleLog "Pulling $model ..." -Level INFO
        & ollama pull $model | Out-Host
        if ($LASTEXITCODE -eq 0) { Add-Line "model:$role" 'OK' "$model pulled" }
        else { Add-Line "model:$role" 'WARN' "pull failed; retry: ollama pull $model" }
    }
}

# -- 5. Initialize project + assign roles -----------------------------------
# `cle init` / `cle model use` act on the CURRENT directory, so anchor them to
# the install folder. This matters especially after UAC self-elevation, where
# the working directory would otherwise be C:\Windows\System32.
Write-CleLog 'Configure' -Level STEP
Push-Location -LiteralPath $RepoRoot
[Environment]::CurrentDirectory = $RepoRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.cle\config.yaml'))) {
        & $cle init | Out-Host
    }
    if (-not $SkipModels -and $daemonUp) {
        $installed = Get-CleModelNames -OllamaListOutput (Invoke-CleCapture -Exe 'ollama' -Arguments @('list'))
        foreach ($role in $recommended.Keys) {
            $model = $recommended[$role]
            if (Test-CleModelInstalled -Installed $installed -Model $model) {
                & $cle model use $role $model | Out-Null
                Add-Line "role:$role" 'OK' "-> $model"
            }
            else {
                Add-Line "role:$role" 'WARN' "$model not installed; role left unset"
            }
        }
    }
}
finally {
    Pop-Location
}

# -- Summary ----------------------------------------------------------------
Write-CleLog 'Summary' -Level STEP
$script:Report | Format-Table -AutoSize Name, Status, Detail | Out-Host
$failed = @($script:Report | Where-Object { $_.Status -eq 'FAIL' })
if ($failed.Count -gt 0) {
    Write-CleLog "Install finished with $($failed.Count) failure(s)." -Level ERROR
    exit 1
}
Write-CleLog 'Install complete. Try:  .\.venv\Scripts\cle.exe doctor' -Level OK
exit 0
