# Supervises prelive-service/main.py: restarts it immediately whenever it exits
# (crash, killed, or intentional stop), forever, until this wrapper itself is
# stopped. Meant to be launched by Windows Task Scheduler at system startup so
# RC-1 (dead daemon, nothing restarts it) can't recur.
#
# Logs go to prelive-service/logs/supervisor.log (rotated by date in filename).

$ErrorActionPreference = "Continue"
$ServiceDir = "D:\INDIAN MARKET\TradingAI\prelive-service"
$Python = "D:\INDIAN MARKET\TradingAI\backtesting-service\.venv\Scripts\python.exe"
$LogDir = Join-Path $ServiceDir "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ServiceDir

while ($true) {
    $stamp = Get-Date -Format "yyyy-MM-dd"
    $logFile = Join-Path $LogDir "prelive_$stamp.log"
    $startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[supervisor] starting main.py at $startedAt"

    & $Python "main.py" *>> $logFile

    $exitCode = $LASTEXITCODE
    $stoppedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[supervisor] main.py exited (code=$exitCode) at $stoppedAt - restarting in 10s"
    Start-Sleep -Seconds 10
}
