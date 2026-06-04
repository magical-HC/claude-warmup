# setup.ps1 — one-time setup for claude-warmup
# Run from the repo root after cloning:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

param(
    [string]$WarmupHome = ""    # override config/state dir (default: ~/.claude-warmup)
)

$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    WARN $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "    FAIL $msg" -ForegroundColor Red; exit 1 }

# ── 1. Python version check ───────────────────────────────────────────────────
Step "Checking Python version"
$pyVer = python -c "import sys; print(sys.version_info.major, sys.version_info.minor)" 2>&1
if ($LASTEXITCODE -ne 0) { Fail "Python not found. Install Python 3.11+ and re-run." }
$major, $minor = $pyVer.Trim().Split(" ")
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 11)) {
    Fail "Python 3.11+ required (found $major.$minor)."
}
Ok "Python $major.$minor"

# ── 2. Install package ────────────────────────────────────────────────────────
Step "Installing claude-warmup (editable)"
python -m pip install -e . -q
if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }
$ver = python -c "import warmup; print(warmup.__version__)"
Ok "claude-warmup $ver installed"

# Locate the warmup.exe installed by pip into the Python Scripts directory.
# Task Scheduler does not inherit the user's PATH, so we need the full path.
$warmupExe = python -c "import sys, pathlib; print(pathlib.Path(sys.executable).parent / 'Scripts' / 'warmup.exe')"
if (-not (Test-Path $warmupExe)) { Fail "warmup.exe not found at $warmupExe — pip install may have failed." }
Ok "warmup command at $warmupExe"

# ── 3. Create default config ──────────────────────────────────────────────────
Step "Initialising config"
if ($WarmupHome -ne "") {
    & $warmupExe init --home $WarmupHome
} else {
    & $warmupExe init
}
if ($LASTEXITCODE -ne 0) { Fail "warmup init failed." }

$cfgPath = if ($WarmupHome -ne "") { Join-Path $WarmupHome "config.toml" } `
           else { Join-Path $env:USERPROFILE ".claude-warmup\config.toml" }
Ok "Config at $cfgPath"

# ── 4. Register recurring monitor task ───────────────────────────────────────
Step "Registering ClaudeWarmup-Monitor (every 15 min)"
$taskCmd = if ($WarmupHome -ne "") { "`"$warmupExe`" monitor --home `"$WarmupHome`"" } `
           else { "`"$warmupExe`" monitor" }
$result = schtasks /Create /TN ClaudeWarmup-Monitor /TR $taskCmd /SC MINUTE /MO 15 /F 2>&1
if ($LASTEXITCODE -ne 0) {
    Warn "Could not register task: $result"
    Warn "Try re-running this script as Administrator."
} else {
    Ok "Task registered"
    schtasks /Run /TN ClaudeWarmup-Monitor | Out-Null
    Start-Sleep -Seconds 4
    $lr = (schtasks /Query /TN ClaudeWarmup-Monitor /FO LIST /V 2>&1 | Select-String "Last Result").Line
    Ok "First run: $($lr.Trim())"
}

# ── 5. Summary ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Edit your peak hours and timezone:"
Write-Host "       notepad `"$cfgPath`""
Write-Host "     Key settings:"
Write-Host "       timezone = `"Asia/Shanghai`"   # your IANA zone"
Write-Host "       start = `"19:00`"  end = `"01:00`"  # cross-midnight ok"
Write-Host ""
Write-Host "  2. Check live window state:"
Write-Host "       warmup status"
Write-Host ""
Write-Host "  3. Get suggestions based on your usage history:"
Write-Host "       warmup advise"
