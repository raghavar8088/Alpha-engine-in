# Idempotent setup: registers all four Task Scheduler tasks that keep the Pre-Live
# Paper Desk + market-data feed alive without a person babysitting them. Safe to
# re-run any time - each task is unregistered first, then re-created.
#
# TradingAI-DhanTokenRotate and TradingAI-PreLiveWatchdog register fine from a
# normal (non-elevated) shell. TradingAI-PreLiveDesk and TradingAI-MarketData use
# AtStartup/AtLogOn triggers, which Windows requires an elevated, truly interactive
# session to register (a non-interactive/automation shell gets Access Denied even
# for AtLogOn alone) - run this script from a real elevated PowerShell
# (right-click PowerShell -> Run as Administrator) to pick those two up:
#   powershell -ExecutionPolicy Bypass -File "D:\INDIAN MARKET\TradingAI\prelive-service\setup_scheduler.ps1"

$ServiceDir = "D:\INDIAN MARKET\TradingAI\prelive-service"
$Python = "D:\INDIAN MARKET\TradingAI\backtesting-service\.venv\Scripts\python.exe"

# 1) Supervisor - runs main.py forever, restarting on any exit. Starts at boot
#    and at logon (covers both a headless boot and a normal desktop session).
# AtStartup requires an elevated (Administrator) shell to register; AtLogOn does not.
# Fall back gracefully if not elevated so this script is still useful either way.
$action1 = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ServiceDir\run_supervised.ps1`""
$trigger1b = New-ScheduledTaskTrigger -AtLogOn
$settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Days 0)
Unregister-ScheduledTask -TaskName "TradingAI-PreLiveDesk" -Confirm:$false -ErrorAction SilentlyContinue
try {
    $trigger1a = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName "TradingAI-PreLiveDesk" -Action $action1 -Trigger @($trigger1a, $trigger1b) `
        -Settings $settings1 -Description "Supervises prelive-service/main.py, restarting it on any crash or reboot." -Force -ErrorAction Stop
    Write-Host "TradingAI-PreLiveDesk registered with AtStartup + AtLogOn (elevated)."
} catch {
    Write-Host "TradingAI-PreLiveDesk registration FAILED (needs elevation): $($_.Exception.Message)"
    Write-Host "  -> Run this script from an elevated ('Run as Administrator') PowerShell to fix."
}

# 2) Daily Dhan token rotation - before 09:15 IST open.
Unregister-ScheduledTask -TaskName "TradingAI-DhanTokenRotate" -Confirm:$false -ErrorAction SilentlyContinue
$action2 = New-ScheduledTaskAction -Execute $Python -Argument "rotate_dhan_token.py" -WorkingDirectory $ServiceDir
$trigger2 = New-ScheduledTaskTrigger -Daily -At "08:45AM"
Register-ScheduledTask -TaskName "TradingAI-DhanTokenRotate" -Action $action2 -Trigger $trigger2 `
    -Description "Refreshes the Dhan access token via TOTP before market open (tokens expire ~daily)." -Force
Write-Host "TradingAI-DhanTokenRotate registered."

# 3) Heartbeat watchdog - every 5 minutes, flags prelive_state if stale during market hours.
Unregister-ScheduledTask -TaskName "TradingAI-PreLiveWatchdog" -Confirm:$false -ErrorAction SilentlyContinue
$action3 = New-ScheduledTaskAction -Execute $Python -Argument "heartbeat_watchdog.py" -WorkingDirectory $ServiceDir
$trigger3 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "TradingAI-PreLiveWatchdog" -Action $action3 -Trigger $trigger3 `
    -Description "Flags prelive_state.heartbeat as stale if >10min old during market hours." -Force
Write-Host "TradingAI-PreLiveWatchdog registered."

# 4) Market-data supervisor - restarts main.py (quote poller) and live_feed.py (bars
#    aggregator), same RC-1-class fix applied to the sibling service whose bars
#    pipeline died silently on 2026-07-10.
$mdServiceDir = "D:\INDIAN MARKET\TradingAI\market-data-service"
$action4 = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$mdServiceDir\run_supervised.ps1`""
Unregister-ScheduledTask -TaskName "TradingAI-MarketData" -Confirm:$false -ErrorAction SilentlyContinue
try {
    $trigger4a = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName "TradingAI-MarketData" -Action $action4 -Trigger @($trigger4a, $trigger1b) `
        -Settings $settings1 -Description "Supervises market-data-service main.py + live_feed.py." -Force -ErrorAction Stop
    Write-Host "TradingAI-MarketData registered with AtStartup + AtLogOn (elevated)."
} catch {
    Write-Host "TradingAI-MarketData registration FAILED (needs elevation): $($_.Exception.Message)"
    Write-Host "  -> Run this script from an elevated ('Run as Administrator') PowerShell to fix."
}

# 5) Pre-market warmup backfill - guarantees bootstrap_history() never seeds a
#    session's strategies from stale bars, independent of whether the live_feed
#    supervisor happened to stay up overnight. Daily 09:05 IST, 10min before open.
Unregister-ScheduledTask -TaskName "TradingAI-WarmupBackfill" -Confirm:$false -ErrorAction SilentlyContinue
$mdPython = "D:\INDIAN MARKET\TradingAI\market-data-service\.venv\Scripts\python.exe"
$action5 = New-ScheduledTaskAction -Execute $mdPython -Argument "warmup_backfill.py" -WorkingDirectory $mdServiceDir
$trigger5 = New-ScheduledTaskTrigger -Daily -At "09:05AM"
Register-ScheduledTask -TaskName "TradingAI-WarmupBackfill" -Action $action5 -Trigger $trigger5 `
    -Description "Backfills 5m/15m/1h NIFTY bars from Dhan history if stale, before every open." -Force
Write-Host "TradingAI-WarmupBackfill registered."

Write-Host "Registered: TradingAI-PreLiveDesk, TradingAI-DhanTokenRotate, TradingAI-PreLiveWatchdog, TradingAI-MarketData, TradingAI-WarmupBackfill"
Write-Host "Verify with: Get-ScheduledTask -TaskName 'TradingAI-*'"
