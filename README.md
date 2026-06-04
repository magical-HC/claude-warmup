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

Clone the repo and run the setup script once — it installs the package, creates
the default config, and registers the background monitor task:

```powershell
git clone https://github.com/magical-HC/claude-warmup.git
cd claude-warmup
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Then edit `~/.claude-warmup/config.toml` to set your peak hours and timezone:

```toml
timezone = "Asia/Shanghai"   # your IANA zone (required on non-English Windows)

[[peak]]
days  = ["Mon","Tue","Wed","Thu","Fri"]
start = "19:00"
end   = "01:00"   # cross-midnight: end < start means next day
```

Check it's working:

```powershell
warmup status   # live window state + next scheduled warmup
warmup advise   # suggestions based on your usage history
```

**To update later:** `git pull` then re-run `scripts\setup.ps1` (idempotent — won't
overwrite your config or duplicate the task).

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
