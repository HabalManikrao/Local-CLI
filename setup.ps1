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

function Show-Usage {
    Write-Host @"
Local CLE - setup.ps1

Usage:
  .\setup.ps1                 Full setup (detect, install, configure, validate)
  .\setup.ps1 -NonInteractive Use defaults, never prompt
  .\setup.ps1 -SkipModels     Skip pulling / configuring Ollama models
  .\setup.ps1 -Repair         Repair only what is broken
  .\setup.ps1 -Verify         Read-only checks (CI-friendly; non-zero on failure)
  .\setup.ps1 -Help           Show this help

Docs: docs\INSTALLATION.md, docs\TROUBLESHOOTING.md
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
    finally { Pop-Location }
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
    $probe = (& $script:VenvPython -c "import cle, typer, rich, httpx, yaml; print(cle.__version__)" 2>&1 | Out-String).Trim()
    $haveCle = ($LASTEXITCODE -eq 0)
    if ($haveCle -and -not $Repair) {
        Add-Check 'Dependencies' 'OK' "cle $probe already installed"
        return $true
    }
    if ($Verify) {
        if ($haveCle) { Add-Check 'Dependencies' 'OK' "cle $probe"; return $true }
        Add-Check 'Dependencies' 'FAIL' 'cle not importable'; return $false
    }

    Write-CleLog 'Upgrading pip ...' -Level INFO
    & $script:VenvPython -m pip install --upgrade pip --disable-pip-version-check -q | Out-Host
    Write-CleLog 'Installing CLE and dependencies (pip install -e ".[dev]") ...' -Level INFO
    & $script:VenvPython -m pip install -e "$RepoRoot[dev]" --disable-pip-version-check | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Stop-WithRemedy 'Dependency installation failed.' "Inspect the output above. Retry:`n  .\.venv\Scripts\python.exe -m pip install -e `".[dev]`""
        Add-Check 'Dependencies' 'FAIL' 'pip install failed'
        return $false
    }
    $ver = (& $script:VenvPython -c "import cle; print(cle.__version__)" 2>&1 | Out-String).Trim()
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
    $roles = Get-CleProjectRoleModels
    $hasFast = ($roles.ContainsKey('fast') -and $roles['fast'])
    if (-not (Test-CleOllamaApi -BaseUrl $baseUrl -TimeoutSec 3)) {
        Add-Check 'Ollama smoke' 'SKIP' 'daemon not reachable' $false; return $true
    }
    if (-not $hasFast) {
        Add-Check 'Ollama smoke' 'SKIP' "no 'fast' model configured" $false; return $true
    }
    Write-CleLog "Asking the model to reply CLE_SETUP_OK (model: $($roles['fast'])) ..." -Level INFO
    $rc = Invoke-Cle -CleArgs @('ask', 'Reply with exactly this token and nothing else: CLE_SETUP_OK')
    $out = $script:LastCleOutput
    if ($rc -eq 0 -and $out -match 'CLE_SETUP_OK') {
        Add-Check 'Ollama smoke' 'OK' 'model generated and CLE processed the response'
        return $true
    }
    Add-Check 'Ollama smoke' 'FAIL' "unexpected response (exit $rc)"
    Write-CleLog ("smoke output: " + ($out.Trim())) -Level DEBUG
    if (-not $Verify) {
        Stop-WithRemedy 'The real Ollama smoke test failed.' "Try manually:`n  .\.venv\Scripts\cle.exe ask `"Reply with exactly: CLE_SETUP_OK`""
    }
    return $false
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

Write-Host ''
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host '            LOCAL CLE - SETUP' -ForegroundColor Cyan
Write-Host ("            Mode: $mode") -ForegroundColor Cyan
Write-Host '==================================================' -ForegroundColor Cyan
Write-CleLog "Mode: $mode; NonInteractive=$NonInteractive; SkipModels=$SkipModels" -Level DEBUG

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
