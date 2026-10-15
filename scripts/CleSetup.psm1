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
    <# Single source of truth for default role -> model mapping. Chosen from
       models already pulled locally so a fresh install needs no downloads. #>
    return [ordered]@{
        fast      = 'tinyllama'
        coding    = 'llama3.1:8b'
        reasoning = 'llama3.1:8b'
        embedding = 'nomic-embed-text'
    }
}

function Get-CleApproxModelSizeGB {
    <# Best-effort download-size hint for the report (GB). 0 if unknown. #>
    [CmdletBinding()]
    param([string]$Model)
    $map = @{
        'tinyllama'        = 0.6
        'llama3.1:8b'      = 4.9
        'nomic-embed-text' = 0.3
        'qwen3:1.7b'       = 1.4
        'gemma4'           = 9.6
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

function Register-CleGlobalCommand {
    <# Make `cle` runnable from any directory by dropping a small wrapper on the
       user's PATH that forwards to the venv's cle.exe. Idempotent; returns the
       wrapper path. A shim (not venv\Scripts on PATH) avoids exposing the
       venv's python/pip globally. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$VenvCleExe)
    $binDir = Join-Path $env:LOCALAPPDATA 'CLE\bin'
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    $shim = Join-Path $binDir 'cle.cmd'
    Set-Content -LiteralPath $shim -Encoding ASCII -Value @('@echo off', "`"$VenvCleExe`" %*")

    # Append to the USER PATH (persisted) if not already present.
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { $userPath = '' }
    $parts = @($userPath -split ';' | Where-Object { $_ -ne '' })
    if ($parts -notcontains $binDir) {
        [Environment]::SetEnvironmentVariable('Path', (@($parts + $binDir) -join ';'), 'User')
    }
    # Also expose it in the current process so it works without a restart here.
    if (($env:Path -split ';') -notcontains $binDir) { $env:Path = "$env:Path;$binDir" }
    return $shim
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

# --------------------------------------------------------------------------
# Offline helpers (Phase 13): checksums, disk, and Ollama model store
# --------------------------------------------------------------------------

function Get-CleFileSha256 {
    <# Lowercase hex SHA256 of a file, or $null if unreadable. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
    }
    catch { return $null }
}

function Test-CleFileSha256 {
    <# True if the file's SHA256 equals $Expected (case-insensitive). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Expected)
    $actual = Get-CleFileSha256 -Path $Path
    if (-not $actual) { return $false }
    return ($actual -eq $Expected.Trim().ToLower())
}

function Format-CleSize {
    <# Human-readable size from a byte count. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][double]$Bytes)
    if ($Bytes -ge 1GB) { return ('{0:N1} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N1} MB' -f ($Bytes / 1MB)) }
    if ($Bytes -ge 1KB) { return ('{0:N1} KB' -f ($Bytes / 1KB)) }
    return ('{0} B' -f [int]$Bytes)
}

function Get-CleFreeDiskGB {
    <# Free space (GB) on the drive that would contain $Path. $null if unknown. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
        $root = [System.IO.Path]::GetPathRoot($full)
        $drive = New-Object System.IO.DriveInfo($root)
        return [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
    }
    catch { return $null }
}

function Get-CleOllamaModelsDir {
    <# Resolve the Ollama model store directory (honors $env:OLLAMA_MODELS). #>
    [CmdletBinding()]
    param()
    if ($env:OLLAMA_MODELS) { return $env:OLLAMA_MODELS }
    return (Join-Path $env:USERPROFILE '.ollama\models')
}

function Resolve-CleModelRef {
    <# Split a model reference into @{ Name; Tag }. Default tag is 'latest'.
       Splits on the LAST ':' so registry ports/namespaces are preserved. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Model)
    $ref = $Model.Trim()
    $idx = $ref.LastIndexOf(':')
    # A ':' that is part of a name (none) vs a tag separator; treat trailing
    # segment without '/' after ':' as the tag.
    if ($idx -gt 0 -and $ref.Substring($idx + 1) -notmatch '/') {
        return @{ Name = $ref.Substring(0, $idx); Tag = $ref.Substring($idx + 1) }
    }
    return @{ Name = $ref; Tag = 'latest' }
}

function ConvertTo-CleBlobFileName {
    <# 'sha256:abc...' -> 'sha256-abc...' (the on-disk blob file name). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Digest)
    return ($Digest -replace ':', '-')
}

function Find-CleOllamaManifest {
    <# Locate a model's manifest file under a models dir. Tries the default
       library path, then a recursive search for <parent=Name>/<file=Tag>.
       Returns the FileInfo full path or $null. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ModelsDir,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Tag
    )
    $manifestsRoot = Join-Path $ModelsDir 'manifests'
    if (-not (Test-Path -LiteralPath $manifestsRoot)) { return $null }
    $default = Join-Path $manifestsRoot ("registry.ollama.ai\library\{0}\{1}" -f ($Name -replace '/', '\'), $Tag)
    if (Test-Path -LiteralPath $default -PathType Leaf) { return $default }
    $leaf = ($Name -split '/')[-1]
    $hit = Get-ChildItem -LiteralPath $manifestsRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $Tag -and (Split-Path -Leaf $_.DirectoryName) -eq $leaf } |
        Select-Object -First 1
    if ($hit) { return $hit.FullName }
    return $null
}

function Get-CleManifestDigests {
    <# Return all blob digests referenced by an Ollama manifest (config + layers). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ManifestPath)
    $digests = @()
    try {
        $j = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    }
    catch { return , $digests }
    if ($j.PSObject.Properties.Name -contains 'config' -and $j.config -and $j.config.digest) {
        $digests += $j.config.digest
    }
    if ($j.PSObject.Properties.Name -contains 'layers' -and $j.layers) {
        foreach ($l in $j.layers) { if ($l.digest) { $digests += $l.digest } }
    }
    return , ($digests | Select-Object -Unique)
}

function Read-CleSha256Sums {
    <# Parse a SHA256SUMS.txt ('hash *relpath' or 'hash  relpath') into a
       hashtable of relpath(forward-slash) -> lowercase hash. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $m = [regex]::Match($t, '^(?<hash>[0-9a-fA-F]{64})\s+\*?(?<path>.+)$')
        if ($m.Success) {
            $rel = $m.Groups['path'].Value.Trim() -replace '\\', '/'
            $map[$rel] = $m.Groups['hash'].Value.ToLower()
        }
    }
    return $map
}

function Test-CleBundleChecksums {
    <# Verify every file listed in a bundle's SHA256SUMS.txt. Returns
       @{ Ok; Checked; Mismatch; Missing; Bad[] } without changing anything. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$BundleDir)
    $sumsPath = Join-Path $BundleDir 'checksums\SHA256SUMS.txt'
    $result = @{ Ok = $false; Checked = 0; Mismatch = 0; Missing = 0; Bad = @() }
    if (-not (Test-Path -LiteralPath $sumsPath)) { $result.Bad += 'SHA256SUMS.txt missing'; return $result }
    $sums = Read-CleSha256Sums -Path $sumsPath
    foreach ($rel in $sums.Keys) {
        $full = Join-Path $BundleDir ($rel -replace '/', '\')
        if (-not (Test-Path -LiteralPath $full)) { $result.Missing++; $result.Bad += "missing: $rel"; continue }
        if (-not (Test-CleFileSha256 -Path $full -Expected $sums[$rel])) { $result.Mismatch++; $result.Bad += "mismatch: $rel"; continue }
        $result.Checked++
    }
    $result.Ok = ($result.Mismatch -eq 0 -and $result.Missing -eq 0 -and $sums.Count -gt 0)
    return $result
}

Export-ModuleMember -Function `
    Initialize-CleLog, Write-CleLog, `
    ConvertTo-CleVersion, Test-CleVersionAtLeast, `
    Get-CleModelNames, Test-CleModelInstalled, `
    ConvertFrom-CleHostUrl, Get-CleConfiguredHost, `
    Get-CleRecommendedModels, Get-CleApproxModelSizeGB, `
    Test-CleCommand, Invoke-CleCapture, Get-ClePython, Get-CleGpu, `
    Get-CleRamGB, Test-CleAdmin, Update-CleProcessPath, Register-CleGlobalCommand, `
    Test-CleOllamaApi, Wait-CleOllamaApi, Install-CleWingetPackage, `
    Get-CleFileSha256, Test-CleFileSha256, Format-CleSize, Get-CleFreeDiskGB, `
    Get-CleOllamaModelsDir, Resolve-CleModelRef, ConvertTo-CleBlobFileName, `
    Find-CleOllamaManifest, Get-CleManifestDigests, Read-CleSha256Sums, `
    Test-CleBundleChecksums
