@echo off
REM Switch console to UTF-8 so Chinese prompts display correctly
REM (Note: chcp 65001 breaks cmd.exe MUI on some Windows builds, causing
REM  "message number 0x2371/0x234a" errors. Keep commented unless Chinese
REM  displays as garbage — the menu below uses choice which doesn't need it.)
REM chcp 65001 >nul

REM ============================================================
REM FinMind Dashboard Launcher
REM - Double-click to launch Flask on port 5000
REM - Uses project venv (.\venv\Scripts\activate.bat)
REM - User picks launch mode:
REM     [1] python.exe  -> foreground, new console window with live output (Ctrl+C to stop)
REM     [2] pythonw.exe -> background, no console window, all output to logs/flask.log
REM - Default = 2 (pythonw, backward-compatible with previous behavior)
REM ============================================================

setlocal

REM --- Resolve project root (parent of this scripts\ folder) ---
REM Buggy: "%~dp0..:~0,-1%" -> ends up as "scripts\." (wrong)
REM Fixed: for-loop resolves ".." to absolute path
for %%I in ("%~dp0\..") do set "PROJECT_DIR=%%~fI"

set PORT=5000
set LOG_DIR=%PROJECT_DIR%\logs
set LOG_FILE=%LOG_DIR%\flask.log

echo ============================================
echo   FinMind Dashboard Launcher
echo ============================================
echo PROJECT_DIR: %PROJECT_DIR%
echo Port:        %PORT%
echo LOG_FILE:    %LOG_FILE%
echo.

REM --- Ask user to choose launch mode (python.exe vs pythonw.exe) ---
echo 請選擇啟動模式：
echo   [1] python.exe  = 前景 (新視窗即時輸出，可按 Ctrl+C 停止)
echo   [2] pythonw.exe = 背景 (無視窗，日誌寫到 logs\flask.log)
echo.
REM Use choice (more robust than set /p — avoids MUI lookup failures
REM  that show "message number 0x2371/0x234a" errors under chcp 65001)
choice /c 12 /n /m "請輸入 1 或 2 (直接按 Enter = 2): "
set "MODE_CHOICE=%ERRORLEVEL%"

if "%MODE_CHOICE%"=="1" (
    set "LAUNCH_MODE=python.exe (foreground / new window)"
) else (
    set "LAUNCH_MODE=pythonw.exe (background / no window)"
)
echo 啟動模式: %LAUNCH_MODE%
echo.

REM --- [1/4] Kill old python processes (works for both modes) ---
REM NOTE: wmic is deprecated/removed on Windows 10 21H1+/11 24H2 and throws
REM "DNS 伺服器不強制需要區域" + "訊息 0x234a" garbage. Use PowerShell + CIM instead.
echo [1/4] Killing old processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -like '*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" 2>nul
timeout /t 2 >nul

REM --- [2/4] Verify venv exists ---
echo [2/4] Checking venv...
if not exist "%PROJECT_DIR%\venv\Scripts\activate.bat" (
    echo [ERROR] venv\Scripts\activate.bat not found.
    echo PROJECT_DIR: %PROJECT_DIR%
    echo To create venv:
    echo     cd /d "%PROJECT_DIR%"
    echo     python -m venv venv
    pause
    exit /b 1
)
echo venv OK.

REM --- [3/4] Ensure logs dir exists ---
echo [3/4] Checking logs directory...
if not exist "%LOG_DIR%" (
    mkdir "%LOG_DIR%" 2>nul
)
echo logs dir OK: %LOG_DIR%

REM --- [4/4] Launch Flask ---
echo [4/4] Starting Flask...
cd /d "%PROJECT_DIR%"
set "PYTHONIOENCODING=utf-8"

if "%MODE_CHOICE%"=="1" (
    echo Opening new console window for python.exe mode...
    REM NOTE: use relative path so we don't need nested quotes inside cmd /k
    start "FinMind Flask python.exe" cmd /k "venv\Scripts\activate.bat && set PYTHONIOENCODING=utf-8 && python app.py"
    echo.
    echo [OK] Flask launched in new console window.
    echo VISIT: http://localhost:%PORT%/
    echo STOP:  close the window, or double-click stop.bat
    echo.
) else (
    echo Starting Flask pythonw + run_hidden.py, background...
    start "" cmd /c "pythonw run_hidden.py"
    echo.
    echo [OK] Flask launched in background, no window.
    echo LOG:     %LOG_FILE%
    echo VISIT:   http://localhost:%PORT%/
    echo STOP:    double-click stop.bat
    echo.
    echo NOTE: No window will appear. Check %LOG_FILE% for output.
    echo.
    REM Auto-close cmd window after 3 seconds, no manual keypress needed
    timeout /t 3 /nobreak >nul
)
