<#
.SYNOPSIS
    Self-contained unit tests for scripts\CleSetup.psm1 (no Pester required).

    Tests the PURE functions (version parsing, model-name parsing, model-install
    matching, URL/host parsing, recommended models). System functions (winget /
    Ollama / GPU) are exercised by setup.ps1 -Verify, not here.

.NOTES
    Exit code 0 = all passed; 1 = one or more failed. CI-friendly.
    Run: powershell -NoProfile -ExecutionPolicy Bypass -File tests\setup\Run-SetupTests.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Import-Module (Join-Path $Root 'scripts\CleSetup.psm1') -Force

$script:Pass = 0
$script:Fail = 0

function Assert-True {
    param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Name)
    if ($Condition) { $script:Pass++; Write-Host "  [PASS] $Name" -ForegroundColor Green }
    else { $script:Fail++; Write-Host "  [FAIL] $Name" -ForegroundColor Red }
}

function Assert-Equal {
    param([Parameter(Mandatory)][string]$Name, $Expected, $Actual)
    $eq = ($Expected -eq $Actual)
    if ($eq) { $script:Pass++; Write-Host "  [PASS] $Name" -ForegroundColor Green }
    else { $script:Fail++; Write-Host "  [FAIL] $Name  (expected '$Expected', got '$Actual')" -ForegroundColor Red }
}

Write-Host 'CleSetup pure-function tests' -ForegroundColor Cyan

# -- ConvertTo-CleVersion ---------------------------------------------------
Write-Host 'ConvertTo-CleVersion'
Assert-Equal 'python string'   '3.12.6' (ConvertTo-CleVersion 'Python 3.12.6').ToString()
Assert-Equal 'git string'      '2.52.0' (ConvertTo-CleVersion 'git version 2.52.0.windows.1').ToString()
Assert-Equal 'two-part pads'   '3.11.0' (ConvertTo-CleVersion 'v3.11').ToString()
Assert-True  ($null -eq (ConvertTo-CleVersion 'no digits here')) 'no version -> null'
Assert-True  ($null -eq (ConvertTo-CleVersion '')) 'empty -> null'

# -- Test-CleVersionAtLeast -------------------------------------------------
Write-Host 'Test-CleVersionAtLeast'
Assert-True  (Test-CleVersionAtLeast 'Python 3.12.6' ([version]'3.11')) '3.12.6 >= 3.11'
Assert-True  (Test-CleVersionAtLeast 'Python 3.11.0' ([version]'3.11')) '3.11.0 >= 3.11'
Assert-True  (-not (Test-CleVersionAtLeast 'Python 3.9.1' ([version]'3.11'))) '3.9.1 < 3.11'
Assert-True  (-not (Test-CleVersionAtLeast 'garbage' ([version]'3.11'))) 'garbage < min'

# -- Get-CleModelNames ------------------------------------------------------
Write-Host 'Get-CleModelNames'
$listOut = "NAME`tID`tSIZE`tMODIFIED`nllama3.2:latest`tabc123`t2.0 GB`t1 day ago`nqwen2.5-coder:7b`tdef456`t4.7 GB`t2 days ago"
$names = Get-CleModelNames -OllamaListOutput $listOut
Assert-Equal 'parsed count'    2 $names.Count
Assert-Equal 'first name'      'llama3.2:latest' $names[0]
Assert-Equal 'second name'     'qwen2.5-coder:7b' $names[1]
$empty = Get-CleModelNames -OllamaListOutput ''
Assert-Equal 'empty -> 0'      0 $empty.Count
$headerOnly = Get-CleModelNames -OllamaListOutput "NAME`tID`tSIZE"
Assert-Equal 'header only -> 0' 0 $headerOnly.Count

# -- Test-CleModelInstalled -------------------------------------------------
Write-Host 'Test-CleModelInstalled'
$inst = @('llama3.2:latest', 'qwen2.5:7b', 'nomic-embed-text:latest')
Assert-True  (Test-CleModelInstalled -Installed $inst -Model 'llama3.2')          'llama3.2 matches :latest'
Assert-True  (Test-CleModelInstalled -Installed $inst -Model 'qwen2.5:7b')        'exact tag match'
Assert-True  (Test-CleModelInstalled -Installed $inst -Model 'nomic-embed-text')  'embed matches :latest'
Assert-True  (-not (Test-CleModelInstalled -Installed $inst -Model 'mistral'))    'absent -> false'
Assert-True  (-not (Test-CleModelInstalled -Installed @() -Model 'anything'))     'empty list -> false'

# -- ConvertFrom-CleHostUrl -------------------------------------------------
Write-Host 'ConvertFrom-CleHostUrl'
$h = ConvertFrom-CleHostUrl 'http://127.0.0.1:11434'
Assert-Equal 'host'            '127.0.0.1' $h.HostName
Assert-Equal 'port'            11434 $h.Port
Assert-Equal 'scheme'          'http' $h.Scheme
$hs = ConvertFrom-CleHostUrl 'https://example.com'
Assert-Equal 'https default port' 443 $hs.Port
Assert-True  ($null -eq (ConvertFrom-CleHostUrl 'not-a-url')) 'invalid -> null'

# -- Get-CleConfiguredHost --------------------------------------------------
Write-Host 'Get-CleConfiguredHost'
$cfgHost = Get-CleConfiguredHost -RepoRoot $Root
Assert-Equal 'reads provider.host' 'http://127.0.0.1:11434' $cfgHost

# -- Recommended models -----------------------------------------------------
Write-Host 'Get-CleRecommendedModels / sizes'
$rec = Get-CleRecommendedModels
Assert-Equal 'four roles'      4 $rec.Keys.Count
Assert-True  ($rec.Contains('fast') -and $rec.Contains('coding') -and $rec.Contains('reasoning') -and $rec.Contains('embedding')) 'all roles present'
Assert-True  ((Get-CleApproxModelSizeGB -Model 'llama3.2') -gt 0) 'known model size > 0'
Assert-Equal 'unknown size 0'  0.0 (Get-CleApproxModelSizeGB -Model 'does-not-exist')

# -- Summary ----------------------------------------------------------------
Write-Host ''
$summaryColor = 'Green'
if ($script:Fail -gt 0) { $summaryColor = 'Red' }
Write-Host ("Result: {0} passed, {1} failed" -f $script:Pass, $script:Fail) -ForegroundColor $summaryColor
if ($script:Fail -gt 0) { exit 1 }
exit 0
