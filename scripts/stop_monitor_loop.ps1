# Stop P2a monitor-loop started by start_monitor_loop.ps1 (weekday ~15:10).
#
# Task Scheduler action example:
#   Program: powershell.exe
#   Arguments:
#     -NoProfile -ExecutionPolicy Bypass -File "C:\fcy\program\stock\scripts\stop_monitor_loop.ps1"
#   Start in: C:\fcy\program\stock

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$StateDir = Join-Path $RepoRoot "data\monitor"
$LogDir = Join-Path $RepoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$PidFile = Join-Path $StateDir "monitor_loop.pid"
$Day = Get-Date -Format "yyyyMMdd"
$CtlLog = Join-Path $LogDir "monitor-loop-ctl-$Day.txt"

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message"
    Add-Content -Path $CtlLog -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    Write-Host $line
}

function Stop-Tree([int]$ProcessId) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Tree -ProcessId $_.ProcessId }
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Log "stopping pid=$ProcessId name=$($proc.ProcessName)"
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Log "stop_monitor_loop cwd=$RepoRoot"

$stopped = @()

if (Test-Path $PidFile) {
    $raw = (Get-Content -Path $PidFile -Raw).Trim()
    if ($raw -match '^\d+$') {
        $wrapperPid = [int]$raw
        if (Get-Process -Id $wrapperPid -ErrorAction SilentlyContinue) {
            Stop-Tree -ProcessId $wrapperPid
            $stopped += $wrapperPid
        } else {
            Write-Log "pid file stale pid=$wrapperPid"
        }
    }
    Remove-Item -Force $PidFile -ErrorAction SilentlyContinue
}

# Fallback: any leftover CLI still matching monitor-loop
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match 'quantagent\.cli' -and
        $_.CommandLine -match 'monitor-loop'
    } |
    ForEach-Object {
        Write-Log "fallback stop pid=$($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped += $_.ProcessId
    }

if ($stopped.Count -eq 0) {
    Write-Log "nothing to stop"
} else {
    Write-Log ("stopped pids=" + (($stopped | Select-Object -Unique) -join ","))
}
exit 0
