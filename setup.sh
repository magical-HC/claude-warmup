#!/usr/bin/env bash
# setup.sh — one-time setup for claude-warmup (Mac / Linux)
# Run from the repo root after cloning:
#   bash setup.sh

set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
step() { printf "\n${CYAN}==> %s${NC}\n" "$*"; }
ok()   { printf "    ${GREEN}OK${NC}  %s\n" "$*"; }
warn() { printf "    ${YELLOW}WARN${NC} %s\n" "$*"; }
fail() { printf "    ${RED}FAIL${NC} %s\n" "$*"; exit 1; }

WARMUP_HOME="${1:-$HOME/.claude-warmup}"

# ── 1. Python version check ───────────────────────────────────────────────────
step "Checking Python version"
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
[ -z "$PY" ] && fail "Python not found. Install Python 3.11+ and re-run."
read -r MAJOR MINOR < <($PY -c "import sys; print(sys.version_info.major, sys.version_info.minor)")
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
    fail "Python 3.11+ required (found $MAJOR.$MINOR)."
fi
ok "Python $MAJOR.$MINOR"

# ── 2. Install package ────────────────────────────────────────────────────────
step "Installing claude-warmup (editable)"
$PY -m pip install -e . -q
VER=$($PY -c "import warmup; print(warmup.__version__)")
ok "claude-warmup $VER installed"

# Locate the warmup executable pip created alongside the Python binary.
WARMUP=$($PY -c "
import sys, pathlib, shutil
# First: alongside the Python executable (venv, brew, system)
candidate = pathlib.Path(sys.executable).parent / 'warmup'
if candidate.exists():
    print(candidate)
else:
    # Second: shutil.which (covers ~/.local/bin and other PATH entries)
    found = shutil.which('warmup')
    print(found if found else pathlib.Path.home() / '.local' / 'bin' / 'warmup')
")
[ -f "$WARMUP" ] || fail "warmup executable not found at $WARMUP. Ensure pip's bin dir is on your PATH."
ok "warmup command at $WARMUP"

# ── 3. Create default config ──────────────────────────────────────────────────
step "Initialising config"
"$WARMUP" init --home "$WARMUP_HOME"
ok "Config at $WARMUP_HOME/config.toml"

# ── 4. Register cron job (every 15 minutes) ───────────────────────────────────
step "Registering cron job (every 15 min)"
CRON_LINE="*/15 * * * * \"$WARMUP\" monitor --home \"$WARMUP_HOME\"  # claude-warmup-monitor"
# Remove previous entry (by marker), then append the new one.
( crontab -l 2>/dev/null | grep -v "claude-warmup-monitor"; echo "$CRON_LINE" ) | crontab -
ok "Cron job registered"
# Trigger once immediately to populate state.json
"$WARMUP" monitor --home "$WARMUP_HOME" && ok "First monitor run: OK" || warn "First monitor run returned non-zero (check config)"

# ── 5. PATH reminder (if warmup not yet on PATH) ──────────────────────────────
if ! command -v warmup &>/dev/null; then
    WARMUP_BIN=$(dirname "$WARMUP")
    warn "warmup is not yet on your PATH."
    warn "Add this to your ~/.bashrc or ~/.zshrc:"
    warn "  export PATH=\"$WARMUP_BIN:\$PATH\""
fi

# ── 6. Summary ────────────────────────────────────────────────────────────────
printf "\n${GREEN}Setup complete.${NC}\n\n"
cat <<EOF
Next steps:
  1. Edit your peak hours and timezone:
       \$EDITOR $WARMUP_HOME/config.toml
     Key settings:
       timezone = "Asia/Shanghai"   # your IANA zone
       start = "19:00"  end = "01:00"  # cross-midnight ok

  2. Check live window state:
       warmup status

  3. Get suggestions based on your usage history:
       warmup advise
EOF
