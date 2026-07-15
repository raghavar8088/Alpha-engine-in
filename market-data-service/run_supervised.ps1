# Supervises market-data-service's two long-lived processes (main.py = quote poller,
# live_feed.py = bars aggregator), restarting either one immediately if it exits.
# Same pattern as prelive-service/run_supervised.ps1 - fixes the same class of bug
# (dead process, nothing restarts it) that caused the bars pipeline outage.

$ErrorActionPreference = "Continue"
$ServiceDir = "D:\INDIAN MARKET\TradingAI\market-data-service"
$Python = "D:\INDIAN MARKET\TradingAI\market-data-service\.venv\Scripts\python.exe"
$LogDir = Join-Path $ServiceDir "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ServiceDir

Start-Job -Name "poller" -ScriptBlock {
    param($Python, $ServiceDir, $LogDir)
    Set-Location $ServiceDir
    while ($true) {
        $stamp = Get-Date -Format "yyyy-MM-dd"
        $logFile = Join-Path $LogDir "poller_$stamp.log"
        Add-Content -Path $logFile -Value "[supervisor] starting main.py at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        & $Python "main.py" *>> $logFile
        Add-Content -Path $logFile -Value "[supervisor] main.py exited (code=$LASTEXITCODE) at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - restarting in 10s"
        Start-Sleep -Seconds 10
    }
} -ArgumentList $Python, $ServiceDir, $LogDir | Out-Null

Start-Job -Name "livefeed" -ScriptBlock {
    param($Python, $ServiceDir, $LogDir)
    Set-Location $ServiceDir
    while ($true) {
        $stamp = Get-Date -Format "yyyy-MM-dd"
        $logFile = Join-Path $LogDir "livefeed_$stamp.log"
        Add-Content -Path $logFile -Value "[supervisor] starting live_feed.py at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        & $Python "live_feed.py" *>> $logFile
        Add-Content -Path $logFile -Value "[supervisor] live_feed.py exited (code=$LASTEXITCODE) at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - restarting in 10s"
        Start-Sleep -Seconds 10
    }
} -ArgumentList $Python, $ServiceDir, $LogDir | Out-Null

# Keep this wrapper process alive so Task Scheduler sees one long-lived parent;
# the two workers above run as background jobs inside it.
while ($true) { Start-Sleep -Seconds 60 }
