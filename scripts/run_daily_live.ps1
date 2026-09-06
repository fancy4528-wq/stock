# Gate 1 daily live once-shot for Windows Task Scheduler.
# Skips non-trading days (same rule as schedule-live-hang).
# Log: data/logs/schedule-live-YYYYMMDD.txt

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $LogDir "schedule-live-$Stamp.txt"

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "cwd=$RepoRoot"

$Uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $Uv) {
    $candidates = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe",
        "$env:USERPROFILE\.local\bin\uv.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $Uv = @{ Source = $c }
            break
        }
    }
}
if (-not $Uv) {
    Write-Log "ERROR: uv not found on PATH"
    exit 1
}
$UvExe = $Uv.Source
Write-Log "uv=$UvExe"

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

Write-Log "starting schedule --once --live"
& $UvExe run python -m quantagent.cli schedule --once --live *>> $LogFile
$code = $LASTEXITCODE
Write-Log "finished exit=$code"
exit $code
