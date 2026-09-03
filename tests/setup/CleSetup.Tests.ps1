<#
    Pester tests for scripts\CleSetup.psm1 (pure functions).

    Compatible with the Pester 3.x that ships with Windows PowerShell 5.1
    (uses `Should Be`, not the v5 `Should -Be`). If you have Pester 5+, the
    self-contained tests\setup\Run-SetupTests.ps1 is the recommended runner.

    Run:  Invoke-Pester -Path tests\setup\CleSetup.Tests.ps1
#>

$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
Import-Module (Join-Path $root 'scripts\CleSetup.psm1') -Force

Describe 'ConvertTo-CleVersion' {
    It 'parses a Python version string' {
        (ConvertTo-CleVersion 'Python 3.12.6').ToString() | Should Be '3.12.6'
    }
    It 'parses a git version string' {
        (ConvertTo-CleVersion 'git version 2.52.0.windows.1').ToString() | Should Be '2.52.0'
    }
    It 'returns $null when there is no version' {
        ConvertTo-CleVersion 'nope' | Should Be $null
    }
}

Describe 'Test-CleVersionAtLeast' {
    It 'accepts an equal-or-greater version' {
        Test-CleVersionAtLeast 'Python 3.12.6' ([version]'3.11') | Should Be $true
    }
    It 'rejects a lower version' {
        Test-CleVersionAtLeast 'Python 3.9.1' ([version]'3.11') | Should Be $false
    }
}

Describe 'Get-CleModelNames' {
    It 'parses names and skips the header' {
        $out = "NAME`tID`tSIZE`nllama3.2:latest`ta`t2 GB`nqwen2.5:7b`tb`t4 GB"
        $names = Get-CleModelNames -OllamaListOutput $out
        $names.Count | Should Be 2
        $names[0] | Should Be 'llama3.2:latest'
    }
    It 'returns an empty array for empty input' {
        (Get-CleModelNames -OllamaListOutput '').Count | Should Be 0
    }
}

Describe 'Test-CleModelInstalled' {
    It 'matches an implicit :latest tag' {
        Test-CleModelInstalled -Installed @('llama3.2:latest') -Model 'llama3.2' | Should Be $true
    }
    It 'reports missing models as false' {
        Test-CleModelInstalled -Installed @('llama3.2:latest') -Model 'mistral' | Should Be $false
    }
}

Describe 'ConvertFrom-CleHostUrl' {
    It 'parses host and port' {
        $h = ConvertFrom-CleHostUrl 'http://127.0.0.1:11434'
        $h.HostName | Should Be '127.0.0.1'
        $h.Port | Should Be 11434
    }
    It 'defaults https to 443' {
        (ConvertFrom-CleHostUrl 'https://example.com').Port | Should Be 443
    }
}

Describe 'Get-CleRecommendedModels' {
    It 'defines all four roles' {
        $r = Get-CleRecommendedModels
        $r.Contains('fast') | Should Be $true
        $r.Contains('coding') | Should Be $true
        $r.Contains('reasoning') | Should Be $true
        $r.Contains('embedding') | Should Be $true
    }
}
