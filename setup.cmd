@echo off
REM Local CLE setup wrapper — runs setup.ps1 with a bypassed execution policy so
REM users never have to change machine-wide PowerShell policy.
REM Usage: setup.cmd [-NonInteractive] [-SkipModels] [-Repair] [-Verify] [-Help]
setlocal
set "HERE=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%setup.ps1" %*
exit /b %ERRORLEVEL%
