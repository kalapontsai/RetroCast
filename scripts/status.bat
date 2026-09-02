@echo off
REM Switch console to UTF-8 so Chinese echo lines display correctly
chcp 65001 >nul

REM FinMind Dashboard 狀態查詢

setlocal
set PORT=5000

echo ============================================
echo   FinMind Dashboard 狀態
echo ============================================
echo.

REM 檢查 port 5000 是否 LISTENING
netstat -ano | findstr :%PORT% | findstr LISTENING >nul
if errorlevel 1 (
    echo [狀態] ❌ 未運行（Port %PORT% 沒人在用）
    echo.
    echo 啟動：雙擊 start.bat
    goto :end
)

echo [狀態] ✅ 運行中

REM 列出相關 python 進程（涵蓋 python.exe 與 pythonw.exe 兩種啟動模式）
REM wmic 已棄用，改用 PowerShell + CIM
echo.
echo [進程]
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -like '*app.py*' } | Select-Object ProcessId,CommandLine | Format-List"

REM 嘗試健康檢查
echo.
echo [健康檢查]
curl -s http://localhost:%PORT%/api/health
echo.
echo.

:end
pause
