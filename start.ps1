# Schedule Assistant - Single Window Launcher
# Usage: Right-click -> "Run with PowerShell"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvActivate = ".\venv\Scripts\activate.bat"
$GatewayLog   = "$ScriptDir\logs\gateway.log"
$PwaLog       = "$ScriptDir\logs\pwa.log"
$LogDir       = "$ScriptDir\logs"

# Ensure log directory exists
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Host.UI.RawUI.WindowTitle = "Schedule Assistant"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Schedule Assistant" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Kill any existing instances
Get-Process -Name "python","nanobot" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# --- Start nanobot gateway (hidden) ---
Write-Host "[1/2] Starting nanobot Gateway..." -ForegroundColor Yellow
$gatewayProc = Start-Process -FilePath ".\venv\Scripts\nanobot.exe" `
    -ArgumentList "gateway" `
    -WorkingDirectory $ScriptDir `
    -WindowStyle Hidden `
    -PassThru

# --- Start PWA server (hidden) ---
Write-Host "[2/2] Starting PWA Frontend..." -ForegroundColor Yellow
$pwaProc = Start-Process -FilePath ".\venv\Scripts\pythonw.exe" `
    -ArgumentList ".\serve_pwa.py" `
    -WorkingDirectory $ScriptDir `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 5

# Verify ports
$gatewayOk = $false
$pwaOk = $false

$ports = netstat -ano 2>$null | Select-String "LISTENING"
if ($ports | Select-String ":18790") { $gatewayOk = $true }
if ($ports | Select-String ":3000")  { $pwaOk = $true }

Write-Host ""
Write-Host "  Gateway (18790): " -NoNewline
if ($gatewayOk) { Write-Host "[OK]" -ForegroundColor Green } else { Write-Host "[FAIL]" -ForegroundColor Red }
Write-Host "  PWA     (3000):  " -NoNewline
if ($pwaOk)     { Write-Host "[OK]" -ForegroundColor Green } else { Write-Host "[FAIL]" -ForegroundColor Red }
Write-Host "  WebSocket(8765): " -NoNewline
if ($ports | Select-String ":8765") { Write-Host "[OK]" -ForegroundColor Green } else { Write-Host "[FAIL]" -ForegroundColor Red }
Write-Host ""
Write-Host "  Open: http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  [R] Restart All   [Q] Quit" -ForegroundColor Gray
Write-Host "============================================" -ForegroundColor Cyan

# --- Monitor Loop ---
$checkCount = 0
while ($true) {
    Start-Sleep -Seconds 5
    $checkCount++

    # Check for key press (non-blocking)
    if ([Console]::KeyAvailable) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq 'Q') {
            Write-Host "`nShutting down..." -ForegroundColor Red
            if ($gatewayProc -and !$gatewayProc.HasExited) { $gatewayProc.Kill() }
            if ($pwaProc -and !$pwaProc.HasExited)     { $pwaProc.Kill() }
            Write-Host "All services stopped. Bye!" -ForegroundColor Gray
            Start-Sleep -Seconds 1
            exit
        }
        if ($key.Key -eq 'R') {
            Write-Host "`nRestarting all services..." -ForegroundColor Yellow
            if ($gatewayProc -and !$gatewayProc.HasExited) { $gatewayProc.Kill() }
            if ($pwaProc -and !$pwaProc.HasExited)     { $pwaProc.Kill() }
            Start-Sleep -Seconds 2
            $gatewayProc = Start-Process -FilePath ".\venv\Scripts\nanobot.exe" -ArgumentList "gateway" -WorkingDirectory $ScriptDir -WindowStyle Hidden -PassThru
            Start-Sleep -Seconds 3
            $pwaProc = Start-Process -FilePath ".\venv\Scripts\pythonw.exe" -ArgumentList ".\serve_pwa.py" -WorkingDirectory $ScriptDir -WindowStyle Hidden -PassThru
            Write-Host "Restarted!" -ForegroundColor Green
        }
    }

    # Every 30 seconds, check health
    if ($checkCount % 6 -ne 0) { continue }

    $ports = netstat -ano 2>$null | Select-String "LISTENING"

    if (-not ($ports | Select-String ":18790")) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Gateway DOWN - restarting..." -ForegroundColor Red
        if ($gatewayProc -and !$gatewayProc.HasExited) { $gatewayProc.Kill() }
        $gatewayProc = Start-Process -FilePath ".\venv\Scripts\nanobot.exe" -ArgumentList "gateway" -WorkingDirectory $ScriptDir -WindowStyle Hidden -PassThru
    }

    if (-not ($ports | Select-String ":3000")) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] PWA DOWN - restarting..." -ForegroundColor Red
        if ($pwaProc -and !$pwaProc.HasExited) { $pwaProc.Kill() }
        $pwaProc = Start-Process -FilePath ".\venv\Scripts\pythonw.exe" -ArgumentList ".\serve_pwa.py" -WorkingDirectory $ScriptDir -WindowStyle Hidden -PassThru
    }
}
