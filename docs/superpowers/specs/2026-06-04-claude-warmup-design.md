# Claude Warmup — Design Spec

**Date:** 2026-06-04
**Status:** Approved design, pending implementation plan

## Problem

Claude Pro/Max plans enforce a rolling **5-hour usage window**. During a long
continuous work session (e.g. 6 hours), if the window happens to anchor at the
start of the session, its quota can be exhausted early and force an idle wait
until the 5h reset. The reset boundary lands at an awkward time.

**Goal:** pre-emptively send a tiny "warmup" message before peak work time so the
5-hour window's reset lands at a useful point (mid-peak), giving the session two
near-full quotas instead of one, and avoiding forced idle gaps.

## Key Mechanism Facts

- The 5-hour window is **account-level**, tied to the Pro/Max subscription — not
  per-surface. Claude Code (CLI), claude.ai web, and the desktop app all draw
  from the **same** rolling window.
- Therefore a single warmup sent via the **Claude Code CLI** (`claude -p`) starts
  the shared account window and covers **both** CLI and web usage. No web
  automation is needed or wanted.
- **Hard requirement:** Claude Code must be authenticated with the **Claude
  subscription login (Pro/Max OAuth)** — the same account as the web. If it uses
  an Anthropic API key, billing is separate and the warmup affects nothing on the
  web. (User confirmed subscription auth.)
- The window is a fixed block **anchored to the first message**. It resets exactly
  5h after the anchor; the *next* message starts a new block. **A warmup only
  creates a new, well-placed anchor when no block is currently active.** If a
  block is already open, a warmup lands inside it and is wasted.
- The **API (pay-as-you-go)** has no comparable rolling reset window (per-minute
  rate limits + monthly spend), so it is **out of scope** for warmup.

## Warmup Math

To position the reset `offset` hours into a peak segment:

```
reset_time  = warmup_time + 5h
warmup_time = peak_start + offset - 5h
```

Default `offset = 2.5h` → warmup fires at `peak_start - 2.5h`, reset lands 2.5h
into peak.

**Worked example** — peak 14:00–20:00 (6h), offset 2.5h:

- Warmup at **11:30** opens block A `[11:30 → 16:30]` (costs ~nothing).
- Work starts 14:00 with block A's quota ~full.
- **16:30** block A resets → block B `[16:30 → 21:30]`, fresh quota.
- Work 16:30–20:00 on block B's fresh quota.
- Net: two near-full quotas across the 6h; boundary at 2.5h in.

**Feasibility check:** if a block is active at the intended warmup time, the
earliest a new anchor can form is the current block's end. The planner shifts the
warmup to `max(ideal_warmup, current_block_end)` and recomputes.

## Approach

Standalone **Python CLI tool** (`warmup`) + **Windows Task Scheduler** for
unattended firing. No persistent daemon. Only the actual warmup ping touches the
API; all monitoring is local-only and cheap.

## Components

| Module | Responsibility |
|---|---|
| `config` | Load/save `config.toml`; defaults. |
| `logreader` | Parse `~/.claude/projects/**/*.jsonl` → `(timestamp, tokens, model)` records. Provides per-hour usage histogram and activity timeline. |
| `window` | From activity timestamps, compute current 5h block anchor/end and "active now?". |
| `monitor` | Live window tracking + necessity decision (see below). Drives the planner. |
| `planner` | **Pure function.** Inputs: peak segments + live window state + offset/band → minimal set of warmup datetimes. Handles feasibility shift and multi-segment logic. |
| `scheduler` | Windows Task Scheduler wrapper (`schtasks` register/update/query/delete). Fixed task names. |
| `sender` | Run `claude -p "<prompt>"` (cheap model), confirm send, record outcome. |
| `advisor` | From `logreader` histogram, find true peak hours; suggest config changes. |
| `cli` | argparse subcommands: `init` / `monitor` / `ping` / `status` / `advise`. |

## Monitor — Live Window Tracking

The window's open/close times are **dynamic** (depend on when the user actually
first messages each day and how blocks chain), so warmup timing *and necessity*
must be driven by live state. A recurring Task Scheduler task runs
`warmup monitor` **every 15 minutes** (local-only, no API call). Each run:

1. Determines when the current block opened (anchor = first message of active block).
2. Projects when it closes to idle (`anchor + 5h`).
3. Makes the **necessity decision** per upcoming peak segment:
   - If the natural reset already lands within **±15 min** of the ideal mid-peak
     point → **no warmup needed**; cancel any pending ping (saves quota).
   - If it lands too early (cold gap before peak), too late, or no block is
     active → schedule/adjust the warmup ping.
   - If a block is open at the ideal warmup moment → defer to `block_end`,
     recompute.

The monitor adjusts/cancels the one-shot `ping` task accordingly.

## Multiple Peak Segments Per Day

Config supports repeated `[[peak]]` blocks (e.g. morning, afternoon, evening).
The planner treats the day as a sequence of segments and produces the **minimal
set of warmups** so that:

- **Each segment starts with a fresh, near-full window.**
- **Reset boundaries are placed in the idle gaps between segments.** If two
  segments are <5h apart, a single window would force them to share one quota, so
  the planner positions a reset in the gap to give each its own near-full quota.
- **Redundant warmups are skipped** via the ±15 min band when a segment is
  already well-covered by a carried-over window or live activity.
- **Long segments (>5h)** keep the in-segment reset behavior.

## Configuration (`config.toml`)

```toml
[warmup]
enabled        = true
offset_hours   = 2.5     # reset lands this far into peak
band_minutes   = 15      # skip warmup if natural reset is within ±this of ideal
warmup_prompt  = "ping"  # minimal throwaway message
model          = "haiku" # cheapest model for the warmup
dry_run        = false

[monitor]
interval_minutes = 15

[[peak]]
days  = ["Mon","Tue","Wed","Thu","Fri"]
start = "09:00"
end   = "11:00"

[[peak]]
days  = ["Mon","Tue","Wed","Thu","Fri"]
start = "14:00"
end   = "17:00"

[[peak]]
days  = ["Mon","Tue","Wed","Thu","Fri"]
start = "20:00"
end   = "23:00"
```

## Data Flow

- **`monitor`** (recurring task, every 15 min, or manual): `logreader → window`
  state + `config` peaks → `planner` → `scheduler` registers/updates/cancels the
  one-shot `ping` task.
- **`ping`** (one-shot task at warmup time): re-check window state → if a block is
  already active, **skip + log why**; else `sender` runs `claude -p`; record
  result; trigger a `monitor` re-evaluation for the next occurrence.
- **`advise`** (manual): `logreader` histogram → `advisor` prints peak hours +
  suggested `offset`/peak edits.
- **`status`** (manual): reads `state.json` → shows live block open time,
  projected close time, whether a warmup is needed, and next warmup time.

A small `state.json` records last warmup time, last result, and next planned warmup.

## Error Handling

- **Auth check** — on `ping`/`status`, confirm subscription mode (not API key);
  warn loudly if it can't be confirmed (warmup would not affect the shared window).
- **`claude` CLI missing / network / rate-limited** — `sender` logs failure to
  `state.json`, retries once, never crashes the task.
- **Already mid-block at warmup time** — skip + record reason (expected).
- **Task Scheduler perms** — register as per-user task (no admin); clear message
  on `schtasks` failure.
- **Timezone/DST** — logs are UTC (`Z`); config + scheduling in local time;
  convert at the boundary; planner is timezone-aware.
- **Idempotency** — fixed task names (`ClaudeWarmup-Monitor`, `ClaudeWarmup-Ping`);
  monitor updates rather than duplicating.

## Testing (TDD)

- **`planner`** (pure) — offset math, ±15 min skip-band, feasibility shift to
  `block_end`, multi-segment gap placement, long-segment in-segment reset,
  DST/timezone edges. The correctness core.
- **`window`** — block anchor/end detection against sample JSONL fixtures.
- **`logreader`** — parsing + per-hour histogram against fixtures.
- **`monitor`** — necessity decisions (skip / schedule / defer) over scripted states.
- **`scheduler` / `sender`** — mocked `schtasks` and `claude` subprocess calls.
- **Integration** — one end-to-end test with `dry_run = true`.

## Out of Scope (this iteration)

- Anthropic API (pay-as-you-go) warmup — no rolling reset window to position.
- claude.ai web browser automation — unnecessary given the shared account window.
- Non-Windows schedulers (cron/launchd) — Windows Task Scheduler only for now.
