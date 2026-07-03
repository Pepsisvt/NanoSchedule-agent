@echo off
cd /d "%~dp0"

echo ============================================
echo   NanoSchedule - Starting Services
echo ============================================
echo.

echo [0] Cleaning up old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| find ":3000 " ^| find "LISTENING" 2^>nul') do (
    echo       Killing old PWA (PID %%a)
    taskkill /F /PID %%a 2>nul
)
for /f "tokens=5" %%a in ('netstat -ano ^| find ":18790 " ^| find "LISTENING" 2^>nul') do (
    echo       Killing old Gateway (PID %%a)
    taskkill /F /PID %%a 2>nul
)
ping -n 2 127.0.0.1 > nul

echo [1/2] Starting Gateway (port 8765/18790)...
start "NanoSchedule-Gateway" cmd /c "cd /d %~dp0 && call venv\Scripts\activate.bat && nanobot gateway"

echo        Waiting for gateway...
ping -n 5 127.0.0.1 > nul

echo [2/2] Starting PWA Frontend (port 3000)...
start "NanoSchedule-PWA" cmd /c "cd /d %~dp0 && call venv\Scripts\activate.bat && python serve_pwa.py"

ping -n 3 127.0.0.1 > nul

echo.
echo ============================================
echo   All services started!
echo.
echo   Frontend : http://localhost:3000
echo   WebSocket: ws://localhost:8765
echo   Gateway  : http://localhost:18790
echo ============================================
echo.
echo   Close this window. Services run independently.
echo.

ping -n 4 127.0.0.1 > nul
exit
