@echo off
REM ===========================================================================
REM  Local CLE — double-click installer
REM
REM  Just double-click this file. It will:
REM    1. ask for Administrator rights (needed so winget can install tools),
REM    2. run install.ps1 with a bypassed execution policy (no policy changes),
REM    3. keep this window open at the end so you can read the result.
REM
REM  Advanced: you can also pass flags, e.g.  install.cmd -SkipModels
REM            or run fully hands-off with   install.cmd -NonInteractive
REM ===========================================================================
setlocal
set "HERE=%~dp0"

REM --- Re-launch elevated if we are not already Administrator -----------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges ^(click "Yes" on the prompt^)...
    if "%~1"=="" (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList '%*'"
    )
    exit /b
)

echo ===========================================================================
echo   Local CLE installer
echo ===========================================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%install.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Install finished successfully.
) else (
    echo Install finished with errors ^(exit code %RC%^). Review the messages above.
)
echo.
echo Press any key to close this window...
pause >nul
exit /b %RC%
