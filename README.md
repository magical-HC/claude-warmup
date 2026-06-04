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

See `config.example.toml`. Key settings:

| Key | Default | Meaning |
|-----|---------|---------|
| `offset_hours` | `2.5` | How far into peak the 5-hour reset lands |
| `band_minutes` | `15` | Skip warmup if natural reset is already within ±this of ideal |
| `timezone` | `""` | IANA zone (e.g. `"Asia/Shanghai"`). Auto-detected on most systems; set explicitly on non-English Windows |

### Defining peak segments

Each `[[peak]]` block is one active work period. Supported end-time formats:

```toml
# Normal: same-day end
[[peak]]
days  = ["Mon","Tue","Wed","Thu","Fri"]
start = "14:00"
end   = "20:00"

# Exactly midnight
[[peak]]
days  = ["Sat","Sun"]
start = "10:00"
end   = "24:00"

# Cross-midnight: end < start means the segment runs into the next day.
# e.g. 20:00 on Monday through 01:00 on Tuesday:
[[peak]]
days  = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
start = "20:00"
end   = "01:00"
```

The `days` list controls which days the segment *starts* on. A cross-midnight
segment always extends into the following day regardless of what days that day
falls on.
