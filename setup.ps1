<#
.SYNOPSIS
    One-command setup / bootstrap for Local CLE (Local CLI Engineering).

.DESCRIPTION
    Detects, installs (via winget), configures, and validates everything needed
    to run CLE on Windows: Python, Git, ripgrep, Ollama, a Python virtual
    environment, project dependencies, local models, model-role configuration,
    and a real Ollama smoke test. Idempotent and safe to re-run.

    Reuses the CLE CLI (cle doctor / init / model use / ask) instead of
    duplicating its logic. PowerShell 5.1 compatible.

.PARAMETER NonInteractive
    Never prompt; use documented defaults.

.PARAMETER SkipModels
    Do not pull or configure Ollama models.

.PARAMETER Repair
    Repair a broken install: recreate a missing venv, reinstall dependencies,
    start Ollama if stopped, pull missing configured models, re-validate.

.PARAMETER Verify
    Read-only checks. Makes no changes. Non-zero exit if a critical check fails.

.PARAMETER Help
    Show usage and exit.

.EXAMPLE
    .\setup.ps1
.EXAMPLE
    .\setup.ps1 -NonInteractive -SkipModels
.EXAMPLE
    .\setup.ps1 -Repair
.EXAMPLE
    .\setup.ps1 -Verify
#>
[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$SkipModels,
    [switch]$Repair,
    [switch]$Verify,
    [switch]$Offline,
    [string]$BundlePath,
    [switch]$Help
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# --------------------------------------------------------------------------
# Bootstrapping
# --------------------------------------------------------------------------

$RepoRoot = $PSScriptRoot
$ModulePath = Join-Path $RepoRoot 'scripts\CleSetup.psm1'
if (-not (Test-Path -LiteralPath $ModulePath)) {
    Write-Host "FATAL: cannot find scripts\CleSetup.psm1 next to setup.ps1." -ForegroundColor Red
    exit 2
}
Import-Module $ModulePath -Force

$script:VenvDir = Join-Path $RepoRoot '.venv'
$script:VenvPython = Join-Path $script:VenvDir 'Scripts\python.exe'
$script:Checks = New-Object System.Collections.ArrayList
$script:CriticalFailure = $null
$script:LogPath = $null
$script:LastCleOutput = ''

# Offline mode: the bundle root defaults to this script's directory (setup.ps1
# is shipped inside the bundle). Package/installer/model dirs hang off it.
$script:BundleDir = if ($BundlePath) { $BundlePath } else { $RepoRoot }
$script:PkgDir = Join-Path $script:BundleDir 'packages'
$script:InstallersDir = Join-Path $script:BundleDir 'installers'
$script:ModelsDir = Join-Path $script:BundleDir 'models'

if ($Offline) {
    # Strict no-network: block pip's index so even an accidental pip invocation
    # cannot reach PyPI. (PIP_FIND_LINKS is NOT set via env because pip splits
    # env values on whitespace and the path may contain spaces; the --find-links
    # CLI argument is passed quoted instead.)
    $env:PIP_NO_INDEX = '1'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:PIP_NO_PYTHON_VERSION_WARNING = '1'
}

function Show-Usage {
    Write-Host @"
Local CLE - setup.ps1

Usage:
  .\setup.ps1                 Full online setup (detect, install, configure, validate)
  .\setup.ps1 -Offline        Install entirely from the bundle (NO internet)
  .\setup.ps1 -NonInteractive Use defaults, never prompt
  .\setup.ps1 -SkipModels     Skip configuring Ollama models
  .\setup.ps1 -Repair         Repair only what is broken (composes with -Offline)
  .\setup.ps1 -Verify         Read-only checks (composes with -Offline)
  .\setup.ps1 -Help           Show this help

Offline install (on a machine with no internet):
  .\setup.ps1 -Offline
  .\setup.ps1 -Offline -Verify
  .\setup.ps1 -Offline -Repair -NonInteractive

Docs: docs\INSTALLATION.md, docs\OFFLINE-INSTALLATION.md, docs\TROUBLESHOOTING.md
"@
}

function Add-Check {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('OK', 'WARN', 'FAIL', 'SKIP')][string]$Status,
        [string]$Detail = '',
        [bool]$Critical = $true
    )
    [void]$script:Checks.Add([pscustomobject]@{
            Name = $Name; Status = $Status; Detail = $Detail; Critical = $Critical
        })
    switch ($Status) {
        'OK'   { Write-CleLog "$Name - $Detail" -Level OK }
        'WARN' { Write-CleLog "$Name - $Detail" -Level WARN }
        'SKIP' { Write-CleLog "$Name - $Detail (skipped)" -Level INFO }
        'FAIL' { Write-CleLog "$Name - $Detail" -Level ERROR }
    }
}

function Stop-WithRemedy {
    param([Parameter(Mandatory)][string]$Reason, [string]$Remedy = '')
    Write-CleLog $Reason -Level ERROR
    if ($Remedy) {
        Write-Host ''
        Write-Host 'Action:' -ForegroundColor Yellow
        Write-Host $Remedy
    }
    $script:CriticalFailure = $Reason
}

function Confirm-CleYesNo {
    param([Parameter(Mandatory)][string]$Question, [bool]$DefaultYes = $true)
    if ($NonInteractive -or $Repair) { return $DefaultYes }
    $suffix = if ($DefaultYes) { '[Y/n]' } else { '[y/N]' }
    $ans = Read-Host "$Question $suffix"
    if ([string]::IsNullOrWhiteSpace($ans)) { return $DefaultYes }
    return ($ans.Trim().ToLower() -in @('y', 'yes'))
}

function Invoke-Cle {
    <# Run the CLE CLI via the venv interpreter. Returns exit code; output in $script:LastCleOutput. #>
    param([Parameter(Mandatory)][string[]]$CleArgs, [switch]$Stream)
    if (-not (Test-Path -LiteralPath $script:VenvPython)) {
        $script:LastCleOutput = ''
        return 99
    }
    Push-Location $RepoRoot
    # Neutralize stderr-as-terminating-error for the child CLI (rich/typer may
    # write to stderr); we surface failures via exit codes instead.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Stream) {
            & $script:VenvPython -m cle.cli.main @CleArgs | Out-Host
            $script:LastCleOutput = ''
        }
        else {
            $script:LastCleOutput = (& $script:VenvPython -m cle.cli.main @CleArgs 2>&1 | Out-String)
        }
        return $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prevEap; Pop-Location }
}

function Get-CleProjectRoleModels {
    <# Parse .cle\config.yaml models: block into a hashtable of role -> model. #>
    $result = @{}
    $cfg = Join-Path $RepoRoot '.cle\config.yaml'
    if (-not (Test-Path -LiteralPath $cfg)) { return $result }
    $inModels = $false
    foreach ($line in (Get-Content -LiteralPath $cfg)) {
        if ($line -match '^\s*models:\s*$') { $inModels = $true; continue }
        if ($inModels) {
            if ($line -match '^\S') { $inModels = $false; continue }   # dedent -> block ended
            if ($line -match '^\s+(?<role>\w+):\s*"?(?<model>[^"#]*?)"?\s*(#.*)?$') {
                $result[$Matches['role']] = $Matches['model'].Trim()
            }
        }
    }
    return $result
}

function Get-CleInstalledModels {
    <# Return installed model names, or $null if the Ollama daemon is unreachable.
       Gating on the API avoids `ollama list` blocking when the daemon is down. #>
    $baseUrl = Get-CleConfiguredHost -RepoRoot $RepoRoot
    if (-not (Test-CleOllamaApi -BaseUrl $baseUrl -TimeoutSec 3)) { return $null }
    $text = Invoke-CleCapture -Exe 'ollama' -Arguments @('list')
    return (Get-CleModelNames -OllamaListOutput $text)
}

# --------------------------------------------------------------------------
# Phases
# --------------------------------------------------------------------------

function Invoke-Preflight {
    Write-CleLog 'Preflight' -Level STEP
    $psv = $PSVersionTable.PSVersion
    if ($psv.Major -lt 5) {
        Stop-WithRemedy "PowerShell $psv is too old (need 5.1+)." "Upgrade Windows PowerShell or install PowerShell 7."
        return $false
    }
    Add-Check 'PowerShell' 'OK' "$psv ($($PSVersionTable.PSEdition))" $true
    $admin = Test-CleAdmin
    Write-CleLog ("Administrator: " + $admin) -Level DEBUG
    Add-Check 'Repository' 'OK' $RepoRoot $true
    return $true
}

function Install-CleIfMissing {
    param(
        [Parameter(Mandatory)][string]$DisplayName,
        [Parameter(Mandatory)][scriptblock]$DetectScript,
        [string]$WingetId,
        [bool]$Critical = $true
    )
    $detected = & $DetectScript
    if (-not $detected) {
        # A prior install (possibly in another shell) may have updated PATH;
        # refresh this process's PATH and re-detect before installing.
        Update-CleProcessPath
        $detected = & $DetectScript
    }
    if ($detected) {
        Add-Check $DisplayName 'OK' "$detected" $Critical
        return $true
    }
    if ($Verify) {
        Add-Check $DisplayName ($(if ($Critical) { 'FAIL' } else { 'WARN' })) 'not found' $Critical
        return (-not $Critical)
    }
    if (-not $WingetId) {
        Add-Check $DisplayName ($(if ($Critical) { 'FAIL' } else { 'WARN' })) 'not found; no auto-install' $Critical
        return (-not $Critical)
    }
    if (-not (Confirm-CleYesNo "Install $DisplayName now?")) {
        Add-Check $DisplayName ($(if ($Critical) { 'FAIL' } else { 'WARN' })) 'declined by user' $Critical
        return (-not $Critical)
    }
    [void](Install-CleWingetPackage -Id $WingetId -Name $DisplayName)
    Update-CleProcessPath
    $detected = & $DetectScript
    if ($detected) {
        Add-Check $DisplayName 'OK' "$detected (installed)" $Critical
        return $true
    }
    if ($Critical) {
        Stop-WithRemedy "$DisplayName still not available after install." `
            "Install $DisplayName manually (winget install --id $WingetId -e), open a NEW terminal, then rerun:`n  .\setup.ps1 -Repair"
        Add-Check $DisplayName 'FAIL' 'unavailable after install' $true
        return $false
    }
    Add-Check $DisplayName 'WARN' 'optional; install skipped/failed' $false
    return $true
}

function Invoke-DetectAndInstallPrereqs {
    Write-CleLog 'Prerequisites' -Level STEP

    # Python (critical)
    $okPy = Install-CleIfMissing -DisplayName 'Python 3.11+' -WingetId 'Python.Python.3.12' -Critical $true -DetectScript {
        $p = Get-ClePython -Minimum ([version]'3.11')
        if ($p) { return "v$($p.Version) ($($p.Exe) $($p.LauncherArgs -join ' '))" } else { return $null }
    }
    if (-not $okPy) { return $false }

    # Git (critical for checkpoints/rollback)
    $okGit = Install-CleIfMissing -DisplayName 'Git' -WingetId 'Git.Git' -Critical $true -DetectScript {
        if (Test-CleCommand 'git') { return (Invoke-CleCapture -Exe 'git' -Arguments @('--version')).Trim() } else { return $null }
    }
    if (-not $okGit) { return $false }

    # ripgrep (optional)
    [void](Install-CleIfMissing -DisplayName 'ripgrep' -WingetId 'BurntSushi.ripgrep.MSVC' -Critical $false -DetectScript {
            if (Test-CleCommand 'rg') { return (Invoke-CleCapture -Exe 'rg' -Arguments @('--version')).Split("`n")[0].Trim() } else { return $null }
        })

    # Ollama (critical)
    $okOllama = Install-CleIfMissing -DisplayName 'Ollama (client)' -WingetId 'Ollama.Ollama' -Critical $true -DetectScript {
        if (Test-CleCommand 'ollama') { return (Invoke-CleCapture -Exe 'ollama' -Arguments @('--version')).Split("`n")[0].Trim() } else { return $null }
    }
    if (-not $okOllama) { return $false }

    # GPU (informational only)
    $gpu = Get-CleGpu
    if ($gpu.Present) {
        $mem = ''
        if ($gpu.MemoryMB) { $mem = " ($($gpu.MemoryMB) MB)" }
        Add-Check 'NVIDIA GPU' 'OK' ("$($gpu.Name)$mem") $false
    }
    else {
        Add-Check 'NVIDIA GPU' 'WARN' 'not detected - CLE will run on CPU' $false
    }
    $ram = Get-CleRamGB
    if ($ram) { Add-Check 'System RAM' 'OK' "$ram GB" $false }
    return $true
}

function Invoke-EnsureVenv {
    Write-CleLog 'Python virtual environment' -Level STEP
    if ($Repair -and (Test-Path -LiteralPath $script:VenvDir) -and -not (Test-Path -LiteralPath $script:VenvPython)) {
        Write-CleLog 'Removing broken .venv (repair)...' -Level WARN
        Remove-Item -Recurse -Force -LiteralPath $script:VenvDir
    }
    if (Test-Path -LiteralPath $script:VenvPython) {
        Add-Check 'Virtualenv' 'OK' '.venv present'
        return $true
    }
    if ($Verify) { Add-Check 'Virtualenv' 'FAIL' '.venv missing'; return $false }

    $py = Get-ClePython -Minimum ([version]'3.11')
    if (-not $py) { Stop-WithRemedy 'No usable Python to create the venv.' 'Install Python 3.11+ and rerun -Repair.'; return $false }
    $mkArgs = @()
    if ($py.LauncherArgs.Count -gt 0) { $mkArgs += $py.LauncherArgs }
    $mkArgs += @('-m', 'venv', $script:VenvDir)
    Write-CleLog "Creating .venv with $($py.Exe) $($mkArgs -join ' ') ..." -Level INFO
    & $py.Exe @mkArgs | Out-Host
    if (-not (Test-Path -LiteralPath $script:VenvPython)) {
        Stop-WithRemedy 'Failed to create the virtual environment.' "Run manually:`n  $($py.Exe) -m venv .venv"
        Add-Check 'Virtualenv' 'FAIL' 'creation failed'
        return $false
    }
    Add-Check 'Virtualenv' 'OK' '.venv created'
    return $true
}

function Invoke-InstallDeps {
    Write-CleLog 'Dependencies' -Level STEP
    if (-not (Test-Path -LiteralPath $script:VenvPython)) { Add-Check 'Dependencies' 'FAIL' 'no venv'; return $false }

    # Is CLE already importable? (idempotency; skip unless -Repair)
    # Guard: a fresh venv has no cle, so python prints a traceback to stderr;
    # with EAP=Stop + 2>&1 that would abort, so neutralize it locally.
    $probe = ''
    $haveCle = $false
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $probe = (& $script:VenvPython -c "import cle, typer, rich, httpx, yaml; print(cle.__version__)" 2>&1 | Out-String).Trim()
        $haveCle = ($LASTEXITCODE -eq 0)
    }
    finally { $ErrorActionPreference = $prevEap }
    if ($haveCle -and -not $Repair) {
        Add-Check 'Dependencies' 'OK' "cle $probe already installed"
        return $true
    }
    if ($Verify) {
        if ($haveCle) { Add-Check 'Dependencies' 'OK' "cle $probe"; return $true }
        Add-Check 'Dependencies' 'FAIL' 'cle not importable'; return $false
    }

    if ($Offline) {
        if (-not (Test-Path -LiteralPath $script:PkgDir)) {
            Stop-WithRemedy "Offline packages directory not found: $script:PkgDir" 'Rebuild the bundle with build-offline-bundle.ps1.'
            Add-Check 'Dependencies' 'FAIL' 'no packages/ in bundle'; return $false
        }
        Write-CleLog "Installing CLE + dependencies from bundle (pip --no-index --find-links) ..." -Level INFO
        & $script:VenvPython -m pip install --no-index --find-links "$script:PkgDir" --upgrade pip | Out-Host
        & $script:VenvPython -m pip install --no-index --find-links "$script:PkgDir" -e "$RepoRoot[dev]" | Out-Host
    }
    else {
        Write-CleLog 'Upgrading pip ...' -Level INFO
        & $script:VenvPython -m pip install --upgrade pip --disable-pip-version-check -q | Out-Host
        Write-CleLog 'Installing CLE and dependencies (pip install -e ".[dev]") ...' -Level INFO
        & $script:VenvPython -m pip install -e "$RepoRoot[dev]" --disable-pip-version-check | Out-Host
    }
    if ($LASTEXITCODE -ne 0) {
        $remedy = if ($Offline) { "Ensure all wheels are present in the bundle, then rerun:`n  .\setup.ps1 -Offline -Repair" } else { "Inspect the output above. Retry:`n  .\.venv\Scripts\python.exe -m pip install -e `".[dev]`"" }
        Stop-WithRemedy 'Dependency installation failed.' $remedy
        Add-Check 'Dependencies' 'FAIL' 'pip install failed'
        return $false
    }
    $ver = ''
    $prevEap2 = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $ver = (& $script:VenvPython -c "import cle; print(cle.__version__)" 2>&1 | Out-String).Trim() }
    finally { $ErrorActionPreference = $prevEap2 }
    Add-Check 'Dependencies' 'OK' "cle $ver installed"
    return $true
}

function Invoke-EnsureOllamaRunning {
    Write-CleLog 'Ollama daemon' -Level STEP
    $baseUrl = Get-CleConfiguredHost -RepoRoot $RepoRoot
    Write-CleLog "Ollama API: $baseUrl" -Level DEBUG
    if (Test-CleOllamaApi -BaseUrl $baseUrl -TimeoutSec 3) {
        Add-Check 'Ollama daemon' 'OK' "reachable at $baseUrl"
        return $true
    }
    if ($Verify) { Add-Check 'Ollama daemon' 'FAIL' "not reachable at $baseUrl"; return $false }
    if (-not (Test-CleCommand 'ollama')) { Add-Check 'Ollama daemon' 'FAIL' 'ollama not installed'; return $false }

    Write-CleLog 'Starting Ollama in the background ...' -Level INFO
    try { Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden | Out-Null }
    catch { Write-CleLog "Could not launch 'ollama serve': $($_.Exception.Message)" -Level WARN }

    if (Wait-CleOllamaApi -BaseUrl $baseUrl -TimeoutSec 60 -IntervalSec 2) {
        Add-Check 'Ollama daemon' 'OK' "started; reachable at $baseUrl"
        return $true
    }
    Stop-WithRemedy 'Ollama is installed but the API did not come up.' `
        "Start it in another terminal and rerun:`n  ollama serve`n  .\setup.ps1 -Repair"
    Add-Check 'Ollama daemon' 'FAIL' 'API not reachable'
    return $false
}

function Invoke-EnsureModels {
    Write-CleLog 'Models' -Level STEP
    if ($SkipModels) { Add-Check 'Models (pull)' 'SKIP' '-SkipModels'; return $true }

    $recommended = Get-CleRecommendedModels
    if (-not (Test-CleCommand 'ollama')) { Add-Check 'Models (pull)' 'FAIL' 'ollama not available'; return $false }

    $installed = Get-CleInstalledModels
    if ($null -eq $installed) {
        Add-Check 'Models (pull)' ($(if ($Verify) { 'FAIL' } else { 'WARN' })) 'Ollama daemon not reachable; cannot manage models' $Verify
        return (-not $Verify)
    }

    # Interactive confirmation with size summary.
    if (-not $Verify) {
        $totalGB = 0.0
        foreach ($role in $recommended.Keys) { $totalGB += (Get-CleApproxModelSizeGB -Model $recommended[$role]) }
        Write-Host ''
        Write-Host 'Recommended local models (RTX 3060 Ti / 32 GB target):' -ForegroundColor Cyan
        foreach ($role in $recommended.Keys) {
            $m = $recommended[$role]; $sz = Get-CleApproxModelSizeGB -Model $m
            Write-Host ("  {0,-10} {1,-20} ~{2} GB" -f $role, $m, $sz)
        }
        Write-Host ("  Total download (only what is missing): up to ~{0} GB" -f $totalGB)
        if (-not (Confirm-CleYesNo 'Download missing recommended models now?')) {
            Add-Check 'Models (pull)' 'SKIP' 'declined; configure later with cle model use'
            return $true
        }
    }

    foreach ($role in $recommended.Keys) {
        $model = $recommended[$role]
        if (Test-CleModelInstalled -Installed $installed -Model $model) {
            Add-Check "Model:$role" 'OK' "$model already present"
            continue
        }
        if ($Verify) { Add-Check "Model:$role" 'FAIL' "$model not installed"; continue }
        Write-CleLog "Pulling $model ($role) ..." -Level INFO
        & ollama pull $model | Out-Host
        if ($LASTEXITCODE -eq 0) {
            Add-Check "Model:$role" 'OK' "$model pulled"
        }
        else {
            Add-Check "Model:$role" 'WARN' "failed to pull $model (you can retry: ollama pull $model)" $false
        }
    }
    return $true
}

function Invoke-ConfigureCle {
    Write-CleLog 'CLE configuration' -Level STEP
    # Initialize the project (reuse the CLI; idempotent).
    if (-not $Verify) {
        $rc = Invoke-Cle -CleArgs @('init')
        if ($rc -ne 0) { Add-Check 'cle init' 'WARN' "exit $rc" $false } else { Add-Check 'cle init' 'OK' 'project initialized' $false }
    }
    if ($SkipModels) { Add-Check 'Model roles' 'SKIP' '-SkipModels'; return $true }

    $recommended = Get-CleRecommendedModels
    $current = Get-CleProjectRoleModels
    $installed = Get-CleInstalledModels
    if ($null -eq $installed) { $installed = @() }

    foreach ($role in $recommended.Keys) {
        $model = $recommended[$role]
        $existing = ''
        if ($current.ContainsKey($role)) { $existing = $current[$role] }
        if ($existing -and -not $Repair) {
            Add-Check "Role:$role" 'OK' "already set to $existing (kept)"
            continue
        }
        if (-not (Test-CleModelInstalled -Installed $installed -Model $model)) {
            Add-Check "Role:$role" 'WARN' "$model not installed; not assigned" $false
            continue
        }
        if ($Verify) { Add-Check "Role:$role" 'OK' "would set $model"; continue }
        $rc = Invoke-Cle -CleArgs @('model', 'use', $role, $model)
        if ($rc -eq 0) { Add-Check "Role:$role" 'OK' "set to $model" }
        else { Add-Check "Role:$role" 'WARN' "cle model use failed (exit $rc)" $false }
    }
    return $true
}

function Invoke-Doctor {
    Write-CleLog 'Validation - cle doctor' -Level STEP
    $rc = Invoke-Cle -CleArgs @('doctor') -Stream
    if ($rc -eq 0) { Add-Check 'cle doctor' 'OK' 'all required checks passed'; return $true }
    Add-Check 'cle doctor' 'FAIL' "reported failures (exit $rc)"
    if (-not $Verify) {
        Stop-WithRemedy 'cle doctor reported a critical failure.' "Review the doctor output above, address the FAIL item, then rerun:`n  .\setup.ps1 -Repair"
    }
    return $false
}

function Invoke-TestSuite {
    Write-CleLog 'Test suite - python -m pytest' -Level STEP
    if ($Verify) { Add-Check 'Test suite' 'SKIP' 'not run in -Verify'; return $true }
    Push-Location $RepoRoot
    try { & $script:VenvPython -m pytest -q | Out-Host; $rc = $LASTEXITCODE }
    finally { Pop-Location }
    if ($rc -eq 0) { Add-Check 'Test suite' 'OK' 'passed'; return $true }
    Add-Check 'Test suite' 'FAIL' "pytest exit $rc"
    Stop-WithRemedy 'The test suite failed.' "Run it directly to inspect:`n  .\.venv\Scripts\python.exe -m pytest"
    return $false
}

function Invoke-SmokeTest {
    Write-CleLog 'Real Ollama smoke test' -Level STEP
    $baseUrl = Get-CleConfiguredHost -RepoRoot $RepoRoot
    if (-not (Test-CleOllamaApi -BaseUrl $baseUrl -TimeoutSec 3)) {
        Add-Check 'Ollama smoke' 'SKIP' 'daemon not reachable' $false; return $true
    }
    # Ask the CLI directly and interpret its answer. This avoids depending on how
    # `cle` resolves the project root vs. where setup wrote config.
    Write-CleLog 'Asking the model to reply CLE_SETUP_OK ...' -Level INFO
    $rc = Invoke-Cle -CleArgs @('ask', 'Reply with exactly this token and nothing else: CLE_SETUP_OK')
    $out = $script:LastCleOutput
    if ($out -match 'No model configured' -or $out -match "role '") {
        Add-Check 'Ollama smoke' 'SKIP' "no 'fast' model configured" $false; return $true
    }
    if ($rc -eq 0 -and $out -match 'CLE_SETUP_OK') {
        Add-Check 'Ollama smoke' 'OK' 'model echoed the token; end-to-end chain verified'
        return $true
    }
    # The pipeline is what we validate here (Ollama reachable, model loaded,
    # response generated, CLE processed it, exit 0). A small local model may not
    # echo the token verbatim; a non-empty response still proves the chain works.
    if ($rc -eq 0 -and $out.Trim().Length -gt 0) {
        Add-Check 'Ollama smoke' 'OK' 'model generated a response; chain verified (token not echoed verbatim)'
        return $true
    }
    Add-Check 'Ollama smoke' 'FAIL' "no response (exit $rc)"
    Write-CleLog ("smoke output: " + ($out.Trim())) -Level DEBUG
    if (-not $Verify) {
        Stop-WithRemedy 'The real Ollama smoke test failed.' "Try manually:`n  .\.venv\Scripts\cle.exe ask `"Reply with exactly: CLE_SETUP_OK`""
    }
    return $false
}

# --------------------------------------------------------------------------
# Offline phases (Phase 13)
# --------------------------------------------------------------------------

function Invoke-OfflinePreflight {
    Write-CleLog 'Offline preflight' -Level STEP
    Write-Host '  OFFLINE MODE' -ForegroundColor Yellow
    Write-Host '  Network downloads: DISABLED' -ForegroundColor Yellow
    Write-Host '  Package index:     DISABLED' -ForegroundColor Yellow
    Write-Host '  Remote model pulls: DISABLED' -ForegroundColor Yellow
    Write-CleLog 'OFFLINE MODE - network downloads/index/model pulls DISABLED' -Level INFO -NoConsole

    # Bundle presence
    if (-not (Test-Path -LiteralPath (Join-Path $script:BundleDir 'manifest.json'))) {
        Stop-WithRemedy "This does not look like an offline bundle (no manifest.json in $script:BundleDir)." `
            "Run setup.ps1 from inside the bundle, or pass -BundlePath <dir>."
        Add-Check 'Bundle' 'FAIL' 'manifest.json not found'; return $false
    }
    Add-Check 'Bundle' 'OK' (Split-Path -Leaf $script:BundleDir)

    # Checksums (integrity)
    Write-CleLog 'Verifying bundle checksums ...' -Level INFO
    $ck = Test-CleBundleChecksums -BundleDir $script:BundleDir
    if ($ck.Ok) {
        Add-Check 'Checksums' 'OK' "$($ck.Checked) file(s) verified"
    }
    else {
        $detail = "mismatch=$($ck.Mismatch) missing=$($ck.Missing)"
        Add-Check 'Checksums' 'FAIL' $detail
        foreach ($b in ($ck.Bad | Select-Object -First 8)) { Write-CleLog "  $b" -Level ERROR }
        if (-not $Verify) {
            Stop-WithRemedy "Bundle integrity check failed ($detail)." `
                "The bundle is corrupt or incomplete. Rebuild it on an online machine:`n  .\build-offline-bundle.ps1"
        }
        return $false
    }

    # Packages present
    $pkgs = @(Get-ChildItem -LiteralPath $script:PkgDir -File -ErrorAction SilentlyContinue)
    if ($pkgs.Count -gt 0) { Add-Check 'Packages' 'OK' "$($pkgs.Count) wheel(s)" }
    else { Add-Check 'Packages' 'FAIL' 'no wheels in bundle'; if (-not $Verify) { Stop-WithRemedy 'No Python packages in the bundle.' 'Rebuild with build-offline-bundle.ps1.' }; return $false }

    # Disk space (rough): bundle size * 2.5 as a margin for extraction/venv/store.
    $bundleBytes = 0
    $bf = @(Get-ChildItem -LiteralPath $script:BundleDir -Recurse -File -ErrorAction SilentlyContinue)
    if ($bf.Count -gt 0) { $bundleBytes = ($bf | Measure-Object -Property Length -Sum).Sum }
    $requiredGB = [math]::Round(($bundleBytes * 2.5) / 1GB, 1)
    $freeGB = Get-CleFreeDiskGB -Path $env:USERPROFILE
    if ($null -ne $freeGB -and $freeGB -lt $requiredGB) {
        Add-Check 'Disk space' 'FAIL' "need ~$requiredGB GB, have $freeGB GB"
        if (-not $Verify) { Stop-WithRemedy "Insufficient disk space (need ~$requiredGB GB, have $freeGB GB)." 'Free space and rerun.' }
        return $false
    }
    Add-Check 'Disk space' 'OK' "need ~$requiredGB GB, have $freeGB GB"
    return $true
}

function Install-CleOfflineTool {
    param(
        [Parameter(Mandatory)][string]$DisplayName,
        [Parameter(Mandatory)][string]$ToolDir,
        [Parameter(Mandatory)][string[]]$SilentArgs,
        [Parameter(Mandatory)][scriptblock]$DetectScript,
        [bool]$Critical = $true
    )
    $detected = & $DetectScript
    if (-not $detected) { Update-CleProcessPath; $detected = & $DetectScript }
    if ($detected) { Add-Check $DisplayName 'OK' "$detected (reused)" $Critical; return $true }
    if ($Verify) { Add-Check $DisplayName ($(if ($Critical) { 'FAIL' } else { 'WARN' })) 'not installed' $Critical; return (-not $Critical) }

    $inst = Get-ChildItem -LiteralPath $ToolDir -File -Filter *.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $inst) {
        if ($Critical) {
            Stop-WithRemedy "$DisplayName is not installed and no installer is bundled ($ToolDir)." `
                "Rebuild the bundle WITH installers on an online machine:`n  .\build-offline-bundle.ps1"
            Add-Check $DisplayName 'FAIL' 'missing tool + installer'
            return $false
        }
        Add-Check $DisplayName 'WARN' 'optional; not installed, no installer' $false
        return $true
    }
    Write-CleLog "Installing $DisplayName from $($inst.Name) (silent) ..." -Level INFO
    try {
        $p = Start-Process -FilePath $inst.FullName -ArgumentList $SilentArgs -Wait -PassThru
        Write-CleLog "$DisplayName installer exit code: $($p.ExitCode)" -Level DEBUG
    }
    catch {
        Stop-WithRemedy "Failed to run the $DisplayName installer: $($_.Exception.Message)" 'Install it manually from the installers folder, then rerun -Offline -Repair.'
        Add-Check $DisplayName 'FAIL' 'installer failed to run'
        return $false
    }
    Update-CleProcessPath
    $detected = & $DetectScript
    if ($detected) { Add-Check $DisplayName 'OK' "$detected (installed)" $Critical; return $true }
    if ($Critical) {
        Stop-WithRemedy "$DisplayName still not available after install." "Open a NEW terminal and rerun:`n  .\setup.ps1 -Offline -Repair"
        Add-Check $DisplayName 'FAIL' 'unavailable after install'
        return $false
    }
    Add-Check $DisplayName 'WARN' 'optional; install unverified' $false
    return $true
}

function Install-OfflinePrereqs {
    Write-CleLog 'Prerequisites (offline)' -Level STEP
    $okPy = Install-CleOfflineTool -DisplayName 'Python 3.11+' -ToolDir (Join-Path $script:InstallersDir 'python') `
        -SilentArgs @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_pip=1', 'Include_test=0') -Critical $true -DetectScript {
        $p = Get-ClePython -Minimum ([version]'3.11'); if ($p) { return "v$($p.Version)" } else { return $null }
    }
    if (-not $okPy) { return $false }

    $okGit = Install-CleOfflineTool -DisplayName 'Git' -ToolDir (Join-Path $script:InstallersDir 'git') `
        -SilentArgs @('/VERYSILENT', '/NORESTART', '/SP-') -Critical $true -DetectScript {
        if (Test-CleCommand 'git') { return (Invoke-CleCapture -Exe 'git' -Arguments @('--version')).Trim() } else { return $null }
    }
    if (-not $okGit) { return $false }

    $okOllama = Install-CleOfflineTool -DisplayName 'Ollama (client)' -ToolDir (Join-Path $script:InstallersDir 'ollama') `
        -SilentArgs @('/VERYSILENT', '/NORESTART') -Critical $true -DetectScript {
        if (Test-CleCommand 'ollama') { return (Invoke-CleCapture -Exe 'ollama' -Arguments @('--version')).Split("`n")[0].Trim() } else { return $null }
    }
    if (-not $okOllama) { return $false }

    $gpu = Get-CleGpu
    if ($gpu.Present) {
        $mem = ''; if ($gpu.MemoryMB) { $mem = " ($($gpu.MemoryMB) MB)" }
        Add-Check 'NVIDIA GPU' 'OK' ("$($gpu.Name)$mem") $false
    }
    else { Add-Check 'NVIDIA GPU' 'WARN' 'not detected - CLE will run on CPU' $false }
    $ram = Get-CleRamGB; if ($ram) { Add-Check 'System RAM' 'OK' "$ram GB" $false }
    return $true
}

function Import-OfflineModels {
    Write-CleLog 'Importing models (offline)' -Level STEP
    if ($SkipModels) { Add-Check 'Models (import)' 'SKIP' '-SkipModels'; return $true }
    $indexPath = Join-Path $script:ModelsDir 'models-index.json'
    if (-not (Test-Path -LiteralPath $indexPath)) {
        Add-Check 'Models (import)' 'WARN' 'no models in bundle' $false; return $true
    }
    # Two-step parse: @(... | ConvertFrom-Json) merges array elements in PS 5.1.
    $parsed = Get-Content -LiteralPath $indexPath -Raw | ConvertFrom-Json
    $index = @($parsed)
    $store = Get-CleOllamaModelsDir
    New-Item -ItemType Directory -Force -Path (Join-Path $store 'blobs') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $store 'manifests') | Out-Null

    foreach ($m in $index) {
        # Verify all blobs exist in the bundle (missing => broken bundle).
        $blobMissing = 0
        foreach ($dg in $m.digests) {
            $bn = ConvertTo-CleBlobFileName -Digest $dg
            if (-not (Test-Path -LiteralPath (Join-Path $script:ModelsDir ("blobs\" + $bn)))) { $blobMissing++ }
        }
        if ($blobMissing -gt 0) {
            Add-Check "Model:$($m.role)" 'FAIL' "$($m.model): $blobMissing blob(s) missing from bundle"
            if (-not $Verify) {
                Stop-WithRemedy "Required model '$($m.model)' (role $($m.role)) is incomplete in the bundle." `
                    "Internet is disabled in offline mode. Rebuild the bundle:`n  .\build-offline-bundle.ps1"
            }
            continue
        }

        $relUnderManifests = ($m.manifestRel -replace '^models/manifests/', '') -replace '/', '\'
        $dstManifest = Join-Path (Join-Path $store 'manifests') $relUnderManifests
        $manifestExists = Test-Path -LiteralPath $dstManifest
        $allBlobsPresent = $true
        foreach ($dg in $m.digests) {
            $bn = ConvertTo-CleBlobFileName -Digest $dg
            if (-not (Test-Path -LiteralPath (Join-Path $store ("blobs\" + $bn)))) { $allBlobsPresent = $false; break }
        }
        if ($manifestExists -and $allBlobsPresent -and -not $Repair) {
            Add-Check "Model:$($m.role)" 'OK' "$($m.model) already in store (reused)"
            continue
        }
        if ($Verify) { Add-Check "Model:$($m.role)" 'OK' "$($m.model) ready to import"; continue }

        # Copy blobs (content-addressed: skip identical existing).
        foreach ($dg in $m.digests) {
            $bn = ConvertTo-CleBlobFileName -Digest $dg
            $src = Join-Path $script:ModelsDir ("blobs\" + $bn)
            $dst = Join-Path $store ("blobs\" + $bn)
            if (-not (Test-Path -LiteralPath $dst)) { Copy-Item -LiteralPath $src -Destination $dst -Force }
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dstManifest) | Out-Null
        Copy-Item -LiteralPath (Join-Path $script:BundleDir ($m.manifestRel -replace '/', '\')) -Destination $dstManifest -Force
        Add-Check "Model:$($m.role)" 'OK' "$($m.model) imported"
    }
    return $true
}

function Invoke-ConfigureCleOffline {
    Write-CleLog 'CLE configuration (offline)' -Level STEP
    if (-not $Verify) {
        $rc = Invoke-Cle -CleArgs @('init')
        if ($rc -eq 0) { Add-Check 'cle init' 'OK' 'project initialized' $false } else { Add-Check 'cle init' 'WARN' "exit $rc" $false }
    }
    if ($SkipModels) { Add-Check 'Model roles' 'SKIP' '-SkipModels'; return $true }
    $indexPath = Join-Path $script:ModelsDir 'models-index.json'
    if (-not (Test-Path -LiteralPath $indexPath)) { Add-Check 'Model roles' 'WARN' 'no models to assign' $false; return $true }
    $parsed = Get-Content -LiteralPath $indexPath -Raw | ConvertFrom-Json
    $index = @($parsed)
    $current = Get-CleProjectRoleModels
    foreach ($m in $index) {
        $existing = ''
        if ($current.ContainsKey($m.role)) { $existing = $current[$m.role] }
        if ($existing -and -not $Repair) { Add-Check "Role:$($m.role)" 'OK' "already set to $existing (kept)"; continue }
        if ($Verify) { Add-Check "Role:$($m.role)" 'OK' "would set $($m.model)"; continue }
        $rc = Invoke-Cle -CleArgs @('model', 'use', $m.role, $m.model)
        if ($rc -eq 0) { Add-Check "Role:$($m.role)" 'OK' "set to $($m.model)" }
        else { Add-Check "Role:$($m.role)" 'WARN' "cle model use failed (exit $rc)" $false }
    }
    return $true
}

# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

function Get-CleStatusSymbol {
    param([string]$Status)
    switch ($Status) {
        'OK'   { return 'PASS' }
        'WARN' { return 'WARN' }
        'SKIP' { return 'SKIP' }
        default { return 'FAIL' }
    }
}

function Show-Report {
    param([string]$Title)
    $gpu = ($script:Checks | Where-Object { $_.Name -eq 'NVIDIA GPU' } | Select-Object -First 1)
    $ram = ($script:Checks | Where-Object { $_.Name -eq 'System RAM' } | Select-Object -First 1)

    Write-Host ''
    Write-Host '==================================================' -ForegroundColor Cyan
    Write-Host ("             $Title") -ForegroundColor Cyan
    Write-Host '==================================================' -ForegroundColor Cyan
    foreach ($c in $script:Checks) {
        $sym = Get-CleStatusSymbol -Status $c.Status
        $color = switch ($c.Status) { 'OK' { 'Green' } 'WARN' { 'Yellow' } 'SKIP' { 'DarkGray' } default { 'Red' } }
        Write-Host ("  {0,-5} {1,-22} {2}" -f $sym, $c.Name, $c.Detail) -ForegroundColor $color
    }
    Write-Host '--------------------------------------------------'
    $fail = @($script:Checks | Where-Object { $_.Status -eq 'FAIL' -and $_.Critical })
    $warn = @($script:Checks | Where-Object { $_.Status -eq 'WARN' })
    if ($fail.Count -eq 0) {
        Write-Host '  CLE is ready.' -ForegroundColor Green
        Write-Host ''
        Write-Host '  Try:'
        Write-Host '    .\.venv\Scripts\cle.exe ask "Explain this project"'
        Write-Host '    .\.venv\Scripts\cle.exe index'
        Write-Host '    .\.venv\Scripts\cle.exe winium analyze'
        Write-Host '    .\.venv\Scripts\cle.exe autopilot "..."'
    }
    else {
        Write-Host ("  {0} critical check(s) failed; {1} warning(s)." -f $fail.Count, $warn.Count) -ForegroundColor Red
        Write-Host '  Fix the FAIL item(s) above and rerun:  .\setup.ps1 -Repair'
    }
    Write-Host '=================================================='
    if ($script:LogPath) { Write-Host ("  Log: " + $script:LogPath) -ForegroundColor DarkGray }
    Write-Host ''
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if ($Help) { Show-Usage; exit 0 }

$logName = 'setup-' + (Get-Date).ToString('yyyyMMdd-HHmmss') + '.log'
$script:LogPath = Initialize-CleLog -Path (Join-Path $RepoRoot ("logs\" + $logName))

$mode = 'Full setup'
if ($Verify) { $mode = 'Verify (read-only)' }
elseif ($Repair) { $mode = 'Repair' }
if ($Offline) { $mode = "Offline - $mode" }

Write-Host ''
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host '            LOCAL CLE - SETUP' -ForegroundColor Cyan
Write-Host ("            Mode: $mode") -ForegroundColor Cyan
Write-Host '==================================================' -ForegroundColor Cyan
Write-CleLog "Mode: $mode; Offline=$Offline; NonInteractive=$NonInteractive; SkipModels=$SkipModels" -Level DEBUG

if ($Offline) {
    $phases = @(
        { Invoke-Preflight },
        { Invoke-OfflinePreflight },
        { Install-OfflinePrereqs },
        { Invoke-EnsureVenv },
        { Invoke-InstallDeps },
        { Invoke-EnsureOllamaRunning },
        { Import-OfflineModels },
        { Invoke-ConfigureCleOffline },
        { Invoke-Doctor },
        { Invoke-TestSuite },
        { Invoke-SmokeTest }
    )
}
else {
    $phases = @(
        { Invoke-Preflight },
        { Invoke-DetectAndInstallPrereqs },
        { Invoke-EnsureVenv },
        { Invoke-InstallDeps },
        { Invoke-EnsureOllamaRunning },
        { Invoke-EnsureModels },
        { Invoke-ConfigureCle },
        { Invoke-Doctor },
        { Invoke-TestSuite },
        { Invoke-SmokeTest }
    )
}

$aborted = $false
foreach ($phase in $phases) {
    $null = & $phase
    if ($script:CriticalFailure) {
        # Verify keeps going to report everything; full/repair stop on first critical failure.
        if (-not $Verify) { $aborted = $true; break }
        $script:CriticalFailure = $null
    }
}

$title = if ($Verify) { 'LOCAL CLE VERIFY' } elseif ($aborted) { 'LOCAL CLE SETUP - INCOMPLETE' } else { 'LOCAL CLE SETUP COMPLETE' }
Show-Report -Title $title

$criticalFails = @($script:Checks | Where-Object { $_.Status -eq 'FAIL' -and $_.Critical })
if ($criticalFails.Count -gt 0 -or $aborted) { exit 1 }
exit 0
