<#
.SYNOPSIS
    Local CLE setup helpers - detection, parsing, logging, and install wrappers.

    Pure functions (parsing/version/model matching/URL/host) are side-effect free
    and unit-tested by tests/setup/CleSetup.Tests.ps1. System functions (winget,
    Ollama, GPU) are thin, defensive wrappers used by setup.ps1.

    PowerShell 5.1 compatible: no &&/||, ternary, ?? or ?. operators.
#>

Set-StrictMode -Version 2.0

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

$script:CleLogFile = $null

function Initialize-CleLog {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $script:CleLogFile = $Path
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    Add-Content -LiteralPath $Path -Value "==== CLE setup log started $stamp ====" -Encoding UTF8
    return $Path
}

function Write-CleLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)][string]$Message,
        [ValidateSet('INFO', 'OK', 'WARN', 'ERROR', 'STEP', 'DEBUG')][string]$Level = 'INFO',
        [switch]$NoConsole
    )
    $stamp = (Get-Date).ToString('HH:mm:ss')
    if ($script:CleLogFile) {
        try { Add-Content -LiteralPath $script:CleLogFile -Value "[$stamp] [$Level] $Message" -Encoding UTF8 } catch { }
    }
    if ($NoConsole) { return }

    $color = 'Gray'; $prefix = ''
    switch ($Level) {
        'OK'    { $color = 'Green';  $prefix = '  [OK]   ' }
        'WARN'  { $color = 'Yellow'; $prefix = '  [WARN] ' }
        'ERROR' { $color = 'Red';    $prefix = '  [FAIL] ' }
        'STEP'  { $color = 'Cyan';   $prefix = '' }
        'DEBUG' { $color = 'DarkGray'; $prefix = '  ' }
        default { $color = 'Gray';   $prefix = '  ' }
    }
    if ($Level -eq 'STEP') {
        Write-Host ''
        Write-Host ("=> " + $Message) -ForegroundColor $color
    }
    else {
        Write-Host ($prefix + $Message) -ForegroundColor $color
    }
}

# --------------------------------------------------------------------------
# Pure parsing / comparison helpers (unit-tested)
# --------------------------------------------------------------------------

function ConvertTo-CleVersion {
    <# Extract the first X.Y or X.Y.Z from arbitrary text as [version]; $null if none. #>
    [CmdletBinding()]
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $m = [regex]::Match($Text, '(\d+)\.(\d+)(?:\.(\d+))?')
    if (-not $m.Success) { return $null }
    $major = [int]$m.Groups[1].Value
    $minor = [int]$m.Groups[2].Value
    $patch = 0
    if ($m.Groups[3].Success) { $patch = [int]$m.Groups[3].Value }
    return (New-Object System.Version($major, $minor, $patch))
}

function Test-CleVersionAtLeast {
    <# True if the version parsed from $Text is >= $Minimum. #>
    [CmdletBinding()]
    param([string]$Text, [Parameter(Mandatory)][version]$Minimum)
    $v = ConvertTo-CleVersion -Text $Text
    if ($null -eq $v) { return $false }
    return ($v -ge $Minimum)
}

function Get-CleModelNames {
    <# Parse `ollama list` text output into an array of model names (first column). #>
    [CmdletBinding()]
    param([string]$OllamaListOutput)
    $names = @()
    if ([string]::IsNullOrWhiteSpace($OllamaListOutput)) { return , $names }
    foreach ($line in ($OllamaListOutput -split "`r?`n")) {
        $t = $line.Trim()
        if (-not $t) { continue }
        if ($t -match '^NAME(\s|$)') { continue }   # header row
        $first = ($t -split '\s+')[0]
        if ($first) { $names += $first }
    }
    return , $names
}

function Test-CleModelInstalled {
    <# True if $Model is present in $Installed, tolerant of implicit :latest. #>
    [CmdletBinding()]
    param([string[]]$Installed, [Parameter(Mandatory)][string]$Model)
    if (-not $Installed) { return $false }
    if ($Installed -contains $Model) { return $true }
    $base = ($Model -split ':', 2)[0]
    foreach ($m in $Installed) {
        if ($m -eq "$base`:latest") { return $true }
        if ($m -eq $base) { return $true }
        $mb = ($m -split ':', 2)[0]
        if ($mb -eq $base) { return $true }
    }
    return $false
}

function ConvertFrom-CleHostUrl {
    <# Parse an http(s) URL into a hashtable @{ Scheme; HostName; Port }; $null if invalid. #>
    [CmdletBinding()]
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $null }
    $m = [regex]::Match($Url.Trim(), '^(?<scheme>https?)://(?<host>[^:/]+)(?::(?<port>\d+))?')
    if (-not $m.Success) { return $null }
    if ($m.Groups['port'].Success) {
        $port = [int]$m.Groups['port'].Value
    }
    elseif ($m.Groups['scheme'].Value -eq 'https') {
        $port = 443
    }
    else {
        $port = 80
    }
    return @{ Scheme = $m.Groups['scheme'].Value; HostName = $m.Groups['host'].Value; Port = $port }
}

function Get-CleConfiguredHost {
    <# Read provider.host from configs/default.yaml (simple line parse); default if absent. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$RepoRoot)
    $default = 'http://127.0.0.1:11434'
    $cfg = Join-Path $RepoRoot 'configs\default.yaml'
    if (-not (Test-Path -LiteralPath $cfg)) { return $default }
    foreach ($line in (Get-Content -LiteralPath $cfg)) {
        if ($line -match '^\s*host:\s*"?(?<h>[^"#]+?)"?\s*(#.*)?$') {
            return $Matches['h'].Trim()
        }
    }
    return $default
}

function Get-CleRecommendedModels {
    <# Single source of truth for default role -> model mapping (RTX 3060 Ti / 32 GB). #>
    return [ordered]@{
        fast      = 'llama3.2'
        coding    = 'qwen2.5-coder:7b'
        reasoning = 'qwen2.5:7b'
        embedding = 'nomic-embed-text'
    }
}

function Get-CleApproxModelSizeGB {
    <# Best-effort download-size hint for the report (GB). 0 if unknown. #>
    [CmdletBinding()]
    param([string]$Model)
    $map = @{
        'llama3.2'         = 2.0
        'qwen2.5-coder:7b' = 4.7
        'qwen2.5:7b'       = 4.7
        'nomic-embed-text' = 0.3
    }
    if ($map.ContainsKey($Model)) { return $map[$Model] }
    return 0.0
}

# --------------------------------------------------------------------------
# System detection (defensive; used by setup.ps1)
# --------------------------------------------------------------------------

function Test-CleCommand {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-CleCapture {
    <# Run a native command and capture combined output as a string (never throws). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Exe, [string[]]$Arguments = @())
    try {
        $out = & $Exe @Arguments 2>&1 | Out-String
        return $out
    }
    catch {
        return ''
    }
}

function Get-ClePython {
    <#
    Locate a usable Python >= $Minimum. Prefers the `py` launcher, avoids the
    Microsoft Store alias (which yields no version). Returns a hashtable
    @{ Exe; LauncherArgs; Version; Source } or $null.
    #>
    [CmdletBinding()]
    param([version]$Minimum = '3.11')
    $candidates = @(
        @{ Exe = 'py';      Args = @('-3.12') },
        @{ Exe = 'py';      Args = @('-3.11') },
        @{ Exe = 'py';      Args = @('-3') },
        @{ Exe = 'python';  Args = @() },
        @{ Exe = 'python3'; Args = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Test-CleCommand -Name $c.Exe)) { continue }
        $verArgs = @()
        if ($c.Args.Count -gt 0) { $verArgs += $c.Args }
        $verArgs += '--version'
        $out = Invoke-CleCapture -Exe $c.Exe -Arguments $verArgs
        $v = ConvertTo-CleVersion -Text $out
        if ($null -eq $v) { continue }         # Store alias / no version -> skip
        if ($v -ge $Minimum) {
            $src = (Get-Command $c.Exe -ErrorAction SilentlyContinue).Source
            return @{ Exe = $c.Exe; LauncherArgs = $c.Args; Version = $v; Source = $src }
        }
    }
    return $null
}

function Get-CleGpu {
    <# Best-effort NVIDIA GPU detection. Returns @{ Present; Name; MemoryMB }. #>
    [CmdletBinding()]
    param()
    $smi = $null
    $cmd = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($cmd) { $smi = $cmd.Source }
    if (-not $smi) {
        $candidates = @(
            (Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'),
            'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe'
        )
        foreach ($p in $candidates) { if (Test-Path -LiteralPath $p) { $smi = $p; break } }
    }
    if (-not $smi) { return @{ Present = $false; Name = $null; MemoryMB = $null } }
    $out = Invoke-CleCapture -Exe $smi -Arguments @('--query-gpu=name,memory.total', '--format=csv,noheader,nounits')
    $line = ($out -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
    if (-not $line) { return @{ Present = $false; Name = $null; MemoryMB = $null } }
    $parts = $line -split ','
    $name = $parts[0].Trim()
    $mem = $null
    if ($parts.Count -gt 1) {
        $mv = ConvertTo-CleVersion -Text $parts[1]
        if ($mv) { $mem = [int]($parts[1].Trim() -replace '[^\d]', '') }
    }
    return @{ Present = $true; Name = $name; MemoryMB = $mem }
}

function Get-CleRamGB {
    [CmdletBinding()]
    param()
    try {
        $bytes = (Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop).TotalPhysicalMemory
        return [math]::Round($bytes / 1GB, 0)
    }
    catch { return $null }
}

function Test-CleAdmin {
    [CmdletBinding()]
    param()
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

function Update-CleProcessPath {
    <# Refresh the current process PATH from Machine + User scopes (post-install). #>
    [CmdletBinding()]
    param()
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @()
    foreach ($p in @($machine, $user)) { if ($p) { $parts += $p } }
    $env:Path = ($parts -join ';')
}

function Test-CleOllamaApi {
    <# True if the Ollama API answers on $BaseUrl/api/tags within $TimeoutSec. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$BaseUrl, [int]$TimeoutSec = 4)
    $uri = ($BaseUrl.TrimEnd('/')) + '/api/tags'
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec $TimeoutSec -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    }
    catch { return $false }
}

function Wait-CleOllamaApi {
    <# Poll the Ollama API until ready or timeout. Returns $true if it came up. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$BaseUrl, [int]$TimeoutSec = 60, [int]$IntervalSec = 2)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-CleOllamaApi -BaseUrl $BaseUrl -TimeoutSec 3) { return $true }
        Start-Sleep -Seconds $IntervalSec
    }
    return (Test-CleOllamaApi -BaseUrl $BaseUrl -TimeoutSec 3)
}

function Install-CleWingetPackage {
    <# Install a package by winget id (idempotent-ish; winget skips if present). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Id, [string]$Name = $null)
    if (-not $Name) { $Name = $Id }
    if (-not (Test-CleCommand -Name 'winget')) {
        Write-CleLog "winget is not available; cannot auto-install $Name." -Level ERROR
        return $false
    }
    Write-CleLog "Installing $Name via winget ($Id) ..." -Level STEP
    $wargs = @('install', '--id', $Id, '-e', '--source', 'winget',
        '--accept-package-agreements', '--accept-source-agreements')
    & winget @wargs | Out-Host
    $code = $LASTEXITCODE
    # winget: 0 = installed; -1978335189 = no applicable upgrade / already installed.
    if ($code -eq 0) { return $true }
    Write-CleLog "winget returned exit code $code for $Name (may already be installed)." -Level WARN
    return $false
}

Export-ModuleMember -Function `
    Initialize-CleLog, Write-CleLog, `
    ConvertTo-CleVersion, Test-CleVersionAtLeast, `
    Get-CleModelNames, Test-CleModelInstalled, `
    ConvertFrom-CleHostUrl, Get-CleConfiguredHost, `
    Get-CleRecommendedModels, Get-CleApproxModelSizeGB, `
    Test-CleCommand, Invoke-CleCapture, Get-ClePython, Get-CleGpu, `
    Get-CleRamGB, Test-CleAdmin, Update-CleProcessPath, `
    Test-CleOllamaApi, Wait-CleOllamaApi, Install-CleWingetPackage
