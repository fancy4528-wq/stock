# Start P2a monitor-loop for Windows Task Scheduler (weekday ~09:20).
# Skips non-trading days (same idea as run_daily_live.ps1).
# PID:  data/monitor/monitor_loop.pid
# Logs: data/logs/monitor-loop-YYYYMMDD.log  (CLI stdout)
#       data/logs/monitor-loop-ctl-YYYYMMDD.txt  (start/stop script)
#
# Task Scheduler action example:
#   Program: powershell.exe
#   Arguments:
#     -NoProfile -ExecutionPolicy Bypass -File "C:\fcy\program\stock\scripts\start_monitor_loop.ps1"
#   Start in: C:\fcy\program\stock

param(
    [string]$Positions = "data/positions/example_cn.yaml",
    [switch]$LiveSpot,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$StateDir = Join-Path $RepoRoot "data\monitor"
$LogDir = Join-Path $RepoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$PidFile = Join-Path $StateDir "monitor_loop.pid"
$Day = Get-Date -Format "yyyyMMdd"
$CtlLog = Join-Path $LogDir "monitor-loop-ctl-$Day.txt"
$OutLog = Join-Path $LogDir "monitor-loop-$Day.log"

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message"
    Add-Content -Path $CtlLog -Value $line -Encoding UTF8
    Write-Host $line
}

function Get-UvExe {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $candidates = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe",
        "$env:USERPROFILE\.local\bin\uv.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Test-MonitorRunning([int]$ProcessId) {
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    return $null -ne $proc
}

Write-Log "start_monitor_loop cwd=$RepoRoot positions=$Positions live_spot=$LiveSpot force=$Force"

if (Test-Path $PidFile) {
    $oldPid = [int](Get-Content -Path $PidFile -Raw).Trim()
    if (Test-MonitorRunning $oldPid) {
        Write-Log "already running pid=$oldPid — exit"
        exit 0
    }
    Write-Log "stale pid file pid=$oldPid — removing"
    Remove-Item -Force $PidFile
}

$UvExe = Get-UvExe
if (-not $UvExe) {
    Write-Log "ERROR: uv not found on PATH"
    exit 1
}
Write-Log "uv=$UvExe"

if (-not $Force) {
    $check = @"
from datetime import date
from quantagent.core.calendar import TradingCalendar
cal = TradingCalendar('CN')
today = date.today()
if cal.is_empty():
    print('SKIP empty_calendar')
    raise SystemExit(0)
if not cal.is_trading_day(today):
    print(f'SKIP not_trading_day={today}')
    raise SystemExit(0)
print(f'RUN trading_day={today}')
"@
    $checkOut = & $UvExe run python -c $check 2>&1 | Out-String
    Write-Log $checkOut.Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: trading-day check failed exit=$LASTEXITCODE"
        exit $LASTEXITCODE
    }
    if ($checkOut -match "SKIP") {
        Write-Log "done (skipped)"
        exit 0
    }
}

$modeFlag = if ($LiveSpot) { "--live-spot" } else { "--demo" }
# cmd.exe wrapper: reliable quoting for paths with spaces; stdout/err append to daily log.
$cmdLine = "/c `"`"$UvExe`" run python -m quantagent.cli monitor-loop --positions `"$Positions`" $modeFlag >> `"$OutLog`" 2>&1`""

Write-Log "launching monitor-loop (detached) out=$OutLog"
$proc = Start-Process -FilePath "cmd.exe" -ArgumentList $cmdLine `
    -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII
Write-Log "started cmd_pid=$($proc.Id)"
exit 0
