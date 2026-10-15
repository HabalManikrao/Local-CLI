@echo off
REM ===========================================================================
REM  Local CLE - quick test (double-click me)
REM  Runs three quick checks so you can see the tool working:
REM    1) cle doctor   2) a quick question   3) a stdin-pipe example
REM  No Administrator rights needed. Run install.cmd first if cle is missing.
REM ===========================================================================
setlocal
set "HERE=%~dp0"
set "CLE=%HERE%.venv\Scripts\cle.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo ===========================================================
echo   Local CLE - quick test
echo ===========================================================

if not exist "%CLE%" (
    echo.
    echo  [!] CLE is not installed yet.
    echo      Double-click install.cmd first, then run this again.
    echo.
    echo Press any key to close...
    pause >nul
    exit /b 1
)

echo.
echo Making sure the Ollama engine is running...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 3 | Out-Null } catch { Start-Process ollama -ArgumentList serve -WindowStyle Hidden; Start-Sleep -Seconds 4 }" >nul 2>&1

echo.
echo ----- 1/3  cle doctor  (environment check) ----------------
"%CLE%" doctor

echo.
echo ----- 2/3  cle ask  (a quick question) --------------------
"%CLE%" ask "In one sentence, what is a Python list comprehension?"

echo.
echo ----- 3/3  pipe test  (feed a file in via stdin) ----------
type "%HERE%README.md" | "%CLE%" ask "Summarize this project in 3 short bullets."

echo.
echo ===========================================================
echo   Test complete. If you saw answers above, it works!
echo ===========================================================
echo.
echo Press any key to close...
pause >nul
exit /b 0
