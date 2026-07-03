@echo off
cd /d "%~dp0"
title NanoSchedule - Keep Alive

echo ============================================
echo   NanoSchedule - Auto Restart Mode
echo   Press Ctrl+C to stop
echo ============================================
echo.

echo Cleaning old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| find ":3000 " ^| find "LISTENING" 2^>nul') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| find ":18790 " ^| find "LISTENING" 2^>nul') do taskkill /F /PID %%a 2>nul
ping -n 2 127.0.0.1 > nul

echo Starting services...
start "NanoSchedule-Gateway" cmd /c "cd /d %~dp0 && call venv\Scripts\activate.bat && nanobot gateway"
ping -n 5 127.0.0.1 > nul
start "NanoSchedule-PWA" cmd /c "cd /d %~dp0 && call venv\Scripts\activate.bat && python serve_pwa.py"
ping -n 3 127.0.0.1 > nul

echo.
echo ============================================
echo   Monitoring (check every 30s)
echo ============================================
echo.

:LOOP
ping -n 31 127.0.0.1 > nul

netstat -ano 2> nul | find ":18790 " > nul
if errorlevel 1 (
    echo [%time%] Gateway DOWN - restarting...
    start "NanoSchedule-Gateway" cmd /c "cd /d %~dp0 && call venv\Scripts\activate.bat && nanobot gateway"
    ping -n 5 127.0.0.1 > nul
)

netstat -ano 2> nul | find ":3000 " > nul
if errorlevel 1 (
    echo [%time%] PWA DOWN - restarting...
    start "NanoSchedule-PWA" cmd /c "cd /d %~dp0 && call venv\Scripts\activate.bat && python serve_pwa.py"
)

goto LOOP
