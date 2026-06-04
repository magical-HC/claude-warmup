# claude-warmup

Pre-warms the Claude **5-hour usage window** before your peak hours so the
window's reset lands mid-peak instead of at an awkward boundary.

## How it works

The 5-hour window is account-level (shared by Claude Code CLI, claude.ai web, and
the desktop app on a Pro/Max plan). A tiny `claude -p` "warmup" message sent
~2.5h before peak starts a fresh window that resets mid-peak, giving your session
two near-full quotas. **Requires Claude Code to be logged in with your Claude
subscription (not an API key).**

A `monitor` task runs every 15 minutes (local-only, no API call), reads your
session logs to see the live window state, and schedules/cancels a one-shot
`ping` task accordingly. Only `ping` calls the API.

## Setup (Windows)

1. `python -m warmup init` — writes `~/.claude-warmup/config.toml`. Edit your peak hours.
   **On non-US-English Windows, set `timezone` to your IANA zone** (e.g.
   `timezone = "Asia/Shanghai"`). Otherwise the tool can't parse the localized
   Windows timezone name and falls back to UTC, putting your peaks at the wrong hours.
2. Register the recurring monitor (run once, in PowerShell):

   ```powershell
   $cmd = '"' + (python -c "import sys;print(sys.executable)") + '" -m warmup monitor'
   schtasks /Create /TN ClaudeWarmup-Monitor /TR $cmd /SC MINUTE /MO 15 /F
   ```
3. `python -m warmup status` — inspect live window state and the next warmup.
4. `python -m warmup advise` — get peak-time suggestions from your usage history.

## Commands

- `warmup init` — create default config.
- `warmup monitor` — recompute and (un)schedule the next warmup. Run by the 15-min task.
- `warmup ping` — send the warmup now (skips if a block is already active). Run by the one-shot task.
- `warmup status` — show live window state and last/next warmup.
- `warmup advise` — suggest peak-time config changes from usage history.

## Config

See `config.example.toml`. `offset_hours` controls how far into peak the reset
lands (default 2.5). `band_minutes` is the tolerance for skipping a redundant
warmup (default 15). `timezone` is an IANA zone name (e.g. `"Asia/Shanghai"`);
leave it empty only if your system locale is US-English, otherwise set it
explicitly so peak hours resolve correctly.
