@echo off
REM Switch console to UTF-8 so Chinese echo lines display correctly
chcp 65001 >nul

REM FinMind Dashboard 停止

setlocal
echo ============================================
echo   FinMind Dashboard 停止
echo ============================================
echo.

echo [1/1] 砍掉 python app.py 進程...
REM wmic 已棄用，改用 PowerShell + CIM
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -like '*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" 2>nul

timeout /t 2 >nul

REM 驗證 port 5000 沒人用
netstat -ano | findstr :5000 | findstr LISTENING >nul
if errorlevel 1 (
    echo [OK] Flask 已停止
) else (
    echo [WARN] Port 5000 仍有進程，請手動檢查
)

echo.
pause
