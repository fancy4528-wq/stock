# Register weekday Task Scheduler jobs for monitor-loop.
# Start 09:20 / Stop 15:10 (local time). Run once in an elevated or normal PowerShell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_monitor_loop_tasks.ps1
#
# Remove later:
#   schtasks /Delete /TN "QuantAgent\MonitorLoopStart" /F
#   schtasks /Delete /TN "QuantAgent\MonitorLoopStop" /F

param(
    [string]$StartTime = "09:20",
    [string]$StopTime = "15:10",
    [switch]$LiveSpot
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$StartScript = Join-Path $RepoRoot "scripts\start_monitor_loop.ps1"
$StopScript = Join-Path $RepoRoot "scripts\stop_monitor_loop.ps1"

if (-not (Test-Path $StartScript)) { throw "missing $StartScript" }
if (-not (Test-Path $StopScript)) { throw "missing $StopScript" }

$startExtra = ""
if ($LiveSpot) { $startExtra = " -LiveSpot" }

$startTr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$StartScript`"$startExtra"
$stopTr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$StopScript`""

# WEEKLY Mon-Fri; /ST is local wall clock.
$common = @("/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/F", "/RL", "LIMITED")

Write-Host "Creating QuantAgent\MonitorLoopStart at $StartTime ..."
& schtasks /Create /TN "QuantAgent\MonitorLoopStart" @common /ST $StartTime /TR $startTr /SD (Get-Date -Format "yyyy/MM/dd")
if ($LASTEXITCODE -ne 0) { throw "schtasks start failed exit=$LASTEXITCODE" }

Write-Host "Creating QuantAgent\MonitorLoopStop at $StopTime ..."
& schtasks /Create /TN "QuantAgent\MonitorLoopStop" @common /ST $StopTime /TR $stopTr /SD (Get-Date -Format "yyyy/MM/dd")
if ($LASTEXITCODE -ne 0) { throw "schtasks stop failed exit=$LASTEXITCODE" }

Write-Host ""
Write-Host "Done. Verify:"
Write-Host '  schtasks /Query /TN "QuantAgent\MonitorLoopStart" /V /FO LIST'
Write-Host '  schtasks /Query /TN "QuantAgent\MonitorLoopStop" /V /FO LIST'
Write-Host ""
Write-Host "Manual test (any day, ignores calendar):"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$StartScript`" -Force"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$StopScript`""
Write-Host ""
Write-Host "Logs: $RepoRoot\data\logs\monitor-loop-YYYYMMDD.log"
Write-Host "Ctl:  $RepoRoot\data\logs\monitor-loop-ctl-YYYYMMDD.txt"
Write-Host "Leave the PC awake (no sleep) on trading mornings; shutdown after work is fine."
