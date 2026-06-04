# Claude Warmup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Windows Python CLI (`warmup`) that, driven by a 15-minute Task Scheduler monitor, sends a tiny `claude -p` "warmup" message before peak hours so the account-level 5-hour usage window resets mid-peak.

**Architecture:** Pure functions for the window math / planning (heavily unit-tested), thin I/O wrappers for log reading, `schtasks`, and the `claude` subprocess. A `monitor` orchestrator runs every 15 min (local-only, no API call), recomputes the optimal warmup time from live session-log state + config peak segments, and registers/cancels a one-shot `ping` task. Only `ping` ever calls the API.

**Tech Stack:** Python 3.14 stdlib only (`tomllib`, `dataclasses`, `datetime`, `zoneinfo`, `subprocess`, `json`, `shutil`), pytest for tests, Windows `schtasks` for scheduling.

---

## File Structure

```
claude_warmup/
  warmup/
    __init__.py        # version, package marker
    config.py          # Config/PeakRule dataclasses, load, default TOML, peaks_for_date
    logreader.py       # ActivityRecord, read_activity, hourly_histogram
    window.py          # WindowState, current_window (5h block detection)
    planner.py         # pure warmup-time math + plan_day orchestrator
    state.py           # State dataclass, load/save state.json
    scheduler.py       # schtasks arg builders + run wrappers, Scheduler class
    sender.py          # claude_available, using_api_key, send_warmup
    monitor.py         # run_monitor orchestration
    advisor.py         # peak_suggestions from histogram
    cli.py             # argparse subcommands: init/monitor/ping/status/advise
    __main__.py        # entrypoint -> cli.main()
  tests/
    conftest.py
    test_config.py
    test_logreader.py
    test_window.py
    test_planner.py
    test_state.py
    test_scheduler.py
    test_sender.py
    test_monitor.py
    test_advisor.py
    test_cli.py
    fixtures/
      sample_session.jsonl
  config.example.toml
  pyproject.toml
  README.md
```

**Conventions used across all tasks:**
- All internal datetimes are **timezone-aware**. Log timestamps are parsed as UTC; peak segments are built in a local `ZoneInfo`. Aware datetimes compare correctly across zones, so no manual conversion is needed for comparisons.
- `BLOCK = timedelta(hours=5)` is defined once in `window.py` and imported elsewhere.
- Pure functions take an explicit `now` argument (never call `datetime.now()` internally) so tests are deterministic.

---

## Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `warmup/__init__.py`, `warmup/__main__.py`, `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "claude-warmup"
version = "0.1.0"
description = "Pre-warm the Claude 5-hour usage window before peak hours"
requires-python = ">=3.11"

[tool.setuptools]
packages = ["warmup"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create package files**

`warmup/__init__.py`:
```python
__version__ = "0.1.0"
```

`warmup/__main__.py`:
```python
from warmup.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

`tests/conftest.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 3: Initialize git and commit**

Note: this directory is not yet a git repo; initialize it (local only, no remote/push).

```bash
git init
git add pyproject.toml warmup/__init__.py warmup/__main__.py tests/conftest.py docs/
git commit -m "chore: scaffold claude-warmup package"
```

Note: `warmup/__main__.py` imports `warmup.cli`, which does not exist until Task 10. That is fine — it is not imported by tests until then. Do not run `python -m warmup` until Task 10.

---

## Task 1: config module

**Files:**
- Create: `warmup/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from warmup.config import Config, PeakRule, load_config, default_config_toml, peaks_for_date


def test_load_config_parses_fields(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(default_config_toml(), encoding="utf-8")
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.enabled is True
    assert cfg.offset_hours == 2.5
    assert cfg.band_minutes == 15
    assert cfg.monitor_interval_minutes == 15
    assert cfg.model == "haiku"
    assert any("Mon" in r.days for r in cfg.peaks)


def test_peaks_for_date_filters_by_weekday():
    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(PeakRule(days=("Mon",), start="14:00", end="20:00"),),
    )
    tz = ZoneInfo("America/New_York")
    # 2026-06-01 is a Monday
    segs = peaks_for_date(cfg, datetime(2026, 6, 1, tzinfo=tz).date(), tz)
    assert len(segs) == 1
    start, end = segs[0]
    assert start.hour == 14 and end.hour == 20
    assert start.tzinfo == tz
    # 2026-06-02 is a Tuesday -> no segments
    assert peaks_for_date(cfg, datetime(2026, 6, 2, tzinfo=tz).date(), tz) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.config'`

- [ ] **Step 3: Write minimal implementation**

`warmup/config.py`:
```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


@dataclass(frozen=True)
class PeakRule:
    days: tuple[str, ...]
    start: str  # "HH:MM"
    end: str    # "HH:MM"


@dataclass(frozen=True)
class Config:
    enabled: bool
    offset_hours: float
    band_minutes: int
    warmup_prompt: str
    model: str
    dry_run: bool
    monitor_interval_minutes: int
    peaks: tuple[PeakRule, ...]


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    w = data.get("warmup", {})
    m = data.get("monitor", {})
    peaks = tuple(
        PeakRule(days=tuple(p["days"]), start=p["start"], end=p["end"])
        for p in data.get("peak", [])
    )
    return Config(
        enabled=bool(w.get("enabled", True)),
        offset_hours=float(w.get("offset_hours", 2.5)),
        band_minutes=int(w.get("band_minutes", 15)),
        warmup_prompt=str(w.get("warmup_prompt", "ping")),
        model=str(w.get("model", "haiku")),
        dry_run=bool(w.get("dry_run", False)),
        monitor_interval_minutes=int(m.get("interval_minutes", 15)),
        peaks=peaks,
    )


def _parse_hhmm(s: str) -> time:
    h, mm = s.split(":")
    return time(int(h), int(mm))


def peaks_for_date(config: Config, d: date, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for rule in config.peaks:
        if not any(WEEKDAYS[day] == d.weekday() for day in rule.days):
            continue
        start = datetime.combine(d, _parse_hhmm(rule.start), tzinfo=tz)
        end = datetime.combine(d, _parse_hhmm(rule.end), tzinfo=tz)
        out.append((start, end))
    return sorted(out)


def default_config_toml() -> str:
    return """\
[warmup]
enabled        = true
offset_hours   = 2.5
band_minutes   = 15
warmup_prompt  = "ping"
model          = "haiku"
dry_run        = false

[monitor]
interval_minutes = 15

[[peak]]
days  = ["Mon","Tue","Wed","Thu","Fri"]
start = "14:00"
end   = "20:00"
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add warmup/config.py tests/test_config.py
git commit -m "feat: config loading and peak-segment resolution"
```

---

## Task 2: logreader module

**Files:**
- Create: `warmup/logreader.py`, `tests/fixtures/sample_session.jsonl`
- Test: `tests/test_logreader.py`

- [ ] **Step 1: Create the fixture**

`tests/fixtures/sample_session.jsonl` (each line is one JSONL record; only the fields the reader needs are present):
```
{"type":"assistant","timestamp":"2026-06-01T18:00:00.000Z","message":{"model":"claude-haiku-4-5","usage":{"input_tokens":100,"output_tokens":50}}}
{"type":"assistant","timestamp":"2026-06-01T18:30:00.000Z","message":{"model":"claude-opus-4-8","usage":{"input_tokens":200,"output_tokens":80}}}
{"type":"user","timestamp":"2026-06-01T18:31:00.000Z","message":{"role":"user","content":"hi"}}
{"type":"summary","summary":"no usage here"}
```

- [ ] **Step 2: Write the failing test**

`tests/test_logreader.py`:
```python
from pathlib import Path
from zoneinfo import ZoneInfo

from warmup.logreader import ActivityRecord, read_jsonl_file, hourly_histogram

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


def test_read_jsonl_file_extracts_assistant_usage():
    records = read_jsonl_file(FIXTURE)
    # Only the two assistant records with usage are returned
    assert len(records) == 2
    assert all(isinstance(r, ActivityRecord) for r in records)
    first = records[0]
    assert first.tokens == 150  # 100 + 50
    assert first.model == "claude-haiku-4-5"
    assert first.timestamp.tzinfo is not None
    assert first.timestamp.utcoffset().total_seconds() == 0  # UTC


def test_hourly_histogram_buckets_by_local_hour():
    records = read_jsonl_file(FIXTURE)
    tz = ZoneInfo("UTC")
    hist = hourly_histogram(records, tz)
    # Both records fall in the 18:00 UTC hour
    assert hist[18] == 150 + 280
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_logreader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.logreader'`

- [ ] **Step 4: Write minimal implementation**

`warmup/logreader.py`:
```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ActivityRecord:
    timestamp: datetime  # tz-aware UTC
    tokens: int
    model: str


def _parse_ts(s: str) -> datetime:
    # Logs use trailing 'Z'; normalize to +00:00 for fromisoformat.
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def read_jsonl_file(path: Path) -> list[ActivityRecord]:
    records: list[ActivityRecord] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            ts = d.get("timestamp")
            if not isinstance(usage, dict) or not ts:
                continue
            tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
            records.append(ActivityRecord(_parse_ts(ts), tokens, str(msg.get("model", "unknown"))))
    return records


def read_activity(claude_dir: Path) -> list[ActivityRecord]:
    records: list[ActivityRecord] = []
    for path in (claude_dir / "projects").rglob("*.jsonl"):
        records.extend(read_jsonl_file(path))
    records.sort(key=lambda r: r.timestamp)
    return records


def hourly_histogram(records: list[ActivityRecord], tz: ZoneInfo) -> dict[int, int]:
    hist: dict[int, int] = {}
    for r in records:
        hour = r.timestamp.astimezone(tz).hour
        hist[hour] = hist.get(hour, 0) + r.tokens
    return hist
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_logreader.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add warmup/logreader.py tests/test_logreader.py tests/fixtures/sample_session.jsonl
git commit -m "feat: parse Claude session logs into activity records"
```

---

## Task 3: window module (5h block detection)

**Files:**
- Create: `warmup/window.py`
- Test: `tests/test_window.py`

- [ ] **Step 1: Write the failing test**

`tests/test_window.py`:
```python
from datetime import datetime, timedelta, timezone

from warmup.logreader import ActivityRecord
from warmup.window import WindowState, current_window, BLOCK


def _rec(h, m=0):
    return ActivityRecord(datetime(2026, 6, 1, h, m, tzinfo=timezone.utc), 10, "x")


def test_no_records_means_inactive():
    ws = current_window([], datetime(2026, 6, 1, 12, tzinfo=timezone.utc))
    assert ws == WindowState(active=False, anchor=None, ends_at=None)


def test_single_block_active_within_5h():
    records = [_rec(10), _rec(11), _rec(12)]
    now = datetime(2026, 6, 1, 13, tzinfo=timezone.utc)
    ws = current_window(records, now)
    assert ws.anchor == datetime(2026, 6, 1, 10, tzinfo=timezone.utc)
    assert ws.ends_at == datetime(2026, 6, 1, 15, tzinfo=timezone.utc)
    assert ws.active is True


def test_new_block_starts_after_5h_gap():
    # 10:00 anchors block A [10-15). 16:00 is past A's end -> anchors block B.
    records = [_rec(10), _rec(16)]
    now = datetime(2026, 6, 1, 17, tzinfo=timezone.utc)
    ws = current_window(records, now)
    assert ws.anchor == datetime(2026, 6, 1, 16, tzinfo=timezone.utc)
    assert ws.ends_at == datetime(2026, 6, 1, 21, tzinfo=timezone.utc)
    assert ws.active is True


def test_inactive_when_now_past_block_end():
    records = [_rec(10)]
    now = datetime(2026, 6, 1, 16, tzinfo=timezone.utc)  # past 15:00 end
    ws = current_window(records, now)
    assert ws.active is False
    assert ws.ends_at == datetime(2026, 6, 1, 15, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.window'`

- [ ] **Step 3: Write minimal implementation**

`warmup/window.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from warmup.logreader import ActivityRecord

BLOCK = timedelta(hours=5)


@dataclass(frozen=True)
class WindowState:
    active: bool
    anchor: datetime | None
    ends_at: datetime | None


def current_window(records: list[ActivityRecord], now: datetime) -> WindowState:
    anchor: datetime | None = None
    for r in sorted(records, key=lambda x: x.timestamp):
        if anchor is None or r.timestamp >= anchor + BLOCK:
            anchor = r.timestamp
    if anchor is None:
        return WindowState(active=False, anchor=None, ends_at=None)
    ends_at = anchor + BLOCK
    return WindowState(active=now < ends_at, anchor=anchor, ends_at=ends_at)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_window.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add warmup/window.py tests/test_window.py
git commit -m "feat: detect current 5-hour usage block from activity"
```

---

## Task 4: planner module (warmup math + multi-segment)

**Files:**
- Create: `warmup/planner.py`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing test**

`tests/test_planner.py`:
```python
from datetime import datetime, timedelta, timezone

from warmup.window import WindowState, BLOCK
from warmup.planner import (
    PlannedWarmup,
    ideal_warmup_time,
    reset_after,
    feasible_warmup_time,
    segment_already_covered,
    plan_day,
)

UTC = timezone.utc


def dt(h, m=0):
    return datetime(2026, 6, 1, h, m, tzinfo=UTC)


def test_ideal_warmup_time_is_offset_minus_block():
    # peak start 14:00, offset 2.5h -> 14:00 + 2.5 - 5 = 11:30
    assert ideal_warmup_time(dt(14), 2.5) == dt(11, 30)


def test_reset_after_adds_block():
    assert reset_after(dt(11, 30)) == dt(16, 30)


def test_feasible_shifts_to_block_end_when_active():
    ideal = dt(11, 30)
    window = WindowState(active=True, anchor=dt(9), ends_at=dt(14))
    now = dt(10)
    # block active until 14:00 -> earliest new anchor is 14:00
    assert feasible_warmup_time(ideal, window, now) == dt(14)


def test_feasible_uses_ideal_when_idle_and_future():
    ideal = dt(11, 30)
    window = WindowState(active=False, anchor=dt(5), ends_at=dt(10))
    now = dt(9)
    assert feasible_warmup_time(ideal, window, now) == dt(11, 30)


def test_segment_already_covered_within_band():
    # ideal reset for segment starting 14:00, offset 2.5 -> 16:30
    assert segment_already_covered(dt(14), dt(16, 40), 2.5, 15) is True   # 10 min off
    assert segment_already_covered(dt(14), dt(17, 0), 2.5, 15) is False   # 30 min off
    assert segment_already_covered(dt(14), None, 2.5, 15) is False


def test_plan_day_single_idle_segment():
    segments = [(dt(14), dt(20))]
    window = WindowState(active=False, anchor=None, ends_at=None)
    plans = plan_day(segments, window, now=dt(8), offset_hours=2.5, band_minutes=15)
    assert plans == [PlannedWarmup(time=dt(11, 30), segment_index=0, reason="scheduled")]


def test_plan_day_skips_segment_covered_by_live_window():
    # Live block ends 16:30, which is exactly the ideal reset for a 14:00 segment.
    segments = [(dt(14), dt(20))]
    window = WindowState(active=True, anchor=dt(11, 30), ends_at=dt(16, 30))
    plans = plan_day(segments, window, now=dt(12), offset_hours=2.5, band_minutes=15)
    assert plans == []  # already covered -> no warmup


def test_plan_day_two_segments_gets_two_warmups():
    # Morning 09-11 and evening 20-23, far apart -> two independent warmups.
    segments = [(dt(9), dt(11)), (dt(20), dt(23))]
    window = WindowState(active=False, anchor=None, ends_at=None)
    plans = plan_day(segments, window, now=dt(3), offset_hours=2.5, band_minutes=15)
    assert [p.segment_index for p in plans] == [0, 1]
    assert plans[0].time == dt(6, 30)   # 09:00 + 2.5 - 5
    assert plans[1].time == dt(17, 30)  # 20:00 + 2.5 - 5


def test_plan_day_ignores_past_segments():
    segments = [(dt(9), dt(11))]
    plans = plan_day(segments, WindowState(False, None, None), now=dt(12),
                     offset_hours=2.5, band_minutes=15)
    assert plans == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_planner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.planner'`

- [ ] **Step 3: Write minimal implementation**

`warmup/planner.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from warmup.window import WindowState, BLOCK


@dataclass(frozen=True)
class PlannedWarmup:
    time: datetime
    segment_index: int
    reason: str


def ideal_warmup_time(segment_start: datetime, offset_hours: float) -> datetime:
    return segment_start + timedelta(hours=offset_hours) - BLOCK


def reset_after(warmup_time: datetime) -> datetime:
    return warmup_time + BLOCK


def feasible_warmup_time(ideal: datetime, window: WindowState, now: datetime) -> datetime:
    candidates = [ideal, now]
    if window.active and window.ends_at is not None:
        candidates.append(window.ends_at)
    return max(candidates)


def segment_already_covered(
    segment_start: datetime,
    projected_reset: datetime | None,
    offset_hours: float,
    band_minutes: int,
) -> bool:
    if projected_reset is None:
        return False
    ideal_reset = segment_start + timedelta(hours=offset_hours)
    delta = abs((projected_reset - ideal_reset).total_seconds())
    return delta <= band_minutes * 60


def plan_day(
    segments: list[tuple[datetime, datetime]],
    window: WindowState,
    now: datetime,
    offset_hours: float,
    band_minutes: int,
) -> list[PlannedWarmup]:
    plans: list[PlannedWarmup] = []
    projected_reset = window.ends_at if window.active else None
    for index, (start, end) in enumerate(sorted(segments)):
        if end <= now:
            continue  # past segment
        if segment_already_covered(start, projected_reset, offset_hours, band_minutes):
            continue  # carried-over window covers it
        ideal = ideal_warmup_time(start, offset_hours)
        warmup_time = feasible_warmup_time(ideal, window, now)
        if warmup_time >= end:
            continue  # too late to help this segment
        plans.append(PlannedWarmup(time=warmup_time, segment_index=index, reason="scheduled"))
        projected_reset = reset_after(warmup_time)
    return plans
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_planner.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add warmup/planner.py tests/test_planner.py
git commit -m "feat: warmup-time planner with multi-segment and skip-band logic"
```

---

## Task 5: state module

**Files:**
- Create: `warmup/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:
```python
from datetime import datetime, timezone
from pathlib import Path

from warmup.state import State, load_state, save_state


def test_roundtrip_state(tmp_path: Path):
    p = tmp_path / "state.json"
    s = State(
        last_warmup=datetime(2026, 6, 1, 11, 30, tzinfo=timezone.utc),
        last_result="ok",
        next_warmup=datetime(2026, 6, 2, 11, 30, tzinfo=timezone.utc),
    )
    save_state(p, s)
    loaded = load_state(p)
    assert loaded == s


def test_load_missing_returns_empty(tmp_path: Path):
    s = load_state(tmp_path / "nope.json")
    assert s == State(last_warmup=None, last_result="", next_warmup=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.state'`

- [ ] **Step 3: Write minimal implementation**

`warmup/state.py`:
```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class State:
    last_warmup: datetime | None
    last_result: str
    next_warmup: datetime | None


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


def _parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def load_state(path: Path) -> State:
    if not path.exists():
        return State(last_warmup=None, last_result="", next_warmup=None)
    data = json.loads(path.read_text(encoding="utf-8"))
    return State(
        last_warmup=_parse(data.get("last_warmup")),
        last_result=data.get("last_result", ""),
        next_warmup=_parse(data.get("next_warmup")),
    )


def save_state(path: Path, state: State) -> None:
    path.write_text(
        json.dumps(
            {
                "last_warmup": _iso(state.last_warmup),
                "last_result": state.last_result,
                "next_warmup": _iso(state.next_warmup),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_state.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add warmup/state.py tests/test_state.py
git commit -m "feat: persist warmup state to json"
```

---

## Task 6: scheduler module (schtasks)

**Files:**
- Create: `warmup/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scheduler.py`:
```python
from datetime import datetime, timezone

from warmup.scheduler import (
    PING_TASK,
    MONITOR_TASK,
    build_register_once_args,
    build_register_minute_args,
    build_delete_args,
    Scheduler,
)


def test_build_register_once_args():
    run_at = datetime(2026, 6, 1, 11, 30, tzinfo=timezone.utc)
    args = build_register_once_args(PING_TASK, run_at, "cmd here")
    assert args[:4] == ["schtasks", "/Create", "/TN", PING_TASK]
    assert "/SC" in args and "ONCE" in args
    assert "11:30" in args
    assert "06/01/2026" in args
    assert args[-1] == "/F"


def test_build_register_minute_args():
    args = build_register_minute_args(MONITOR_TASK, 15, "cmd here")
    assert "MINUTE" in args
    assert "/MO" in args and "15" in args


def test_build_delete_args():
    assert build_delete_args(PING_TASK) == ["schtasks", "/Delete", "/TN", PING_TASK, "/F"]


def test_scheduler_register_ping_invokes_runner():
    calls = []
    sched = Scheduler(command="my-cmd", runner=lambda args: calls.append(args))
    sched.register_ping(datetime(2026, 6, 1, 11, 30, tzinfo=timezone.utc))
    assert len(calls) == 1
    assert calls[0][:2] == ["schtasks", "/Create"]
    assert "my-cmd" in calls[0]


def test_scheduler_cancel_ping_invokes_delete():
    calls = []
    sched = Scheduler(command="my-cmd", runner=lambda args: calls.append(args))
    sched.cancel_ping()
    assert calls == [["schtasks", "/Delete", "/TN", PING_TASK, "/F"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.scheduler'`

- [ ] **Step 3: Write minimal implementation**

`warmup/scheduler.py`:
```python
from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Callable

PING_TASK = "ClaudeWarmup-Ping"
MONITOR_TASK = "ClaudeWarmup-Monitor"


def build_register_once_args(task: str, run_at: datetime, command: str) -> list[str]:
    return [
        "schtasks", "/Create", "/TN", task, "/TR", command,
        "/SC", "ONCE",
        "/ST", run_at.strftime("%H:%M"),
        "/SD", run_at.strftime("%m/%d/%Y"),
        "/F",
    ]


def build_register_minute_args(task: str, interval_minutes: int, command: str) -> list[str]:
    return [
        "schtasks", "/Create", "/TN", task, "/TR", command,
        "/SC", "MINUTE", "/MO", str(interval_minutes),
        "/F",
    ]


def build_delete_args(task: str) -> list[str]:
    return ["schtasks", "/Delete", "/TN", task, "/F"]


def _default_runner(args: list[str]) -> None:
    subprocess.run(args, capture_output=True, text=True, check=False)


class Scheduler:
    def __init__(self, command: str, runner: Callable[[list[str]], None] = _default_runner):
        self.command = command
        self.runner = runner

    def register_ping(self, run_at: datetime) -> None:
        self.runner(build_register_once_args(PING_TASK, run_at, self.command))

    def cancel_ping(self) -> None:
        self.runner(build_delete_args(PING_TASK))

    def register_monitor(self, interval_minutes: int, command: str) -> None:
        self.runner(build_register_minute_args(MONITOR_TASK, interval_minutes, command))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add warmup/scheduler.py tests/test_scheduler.py
git commit -m "feat: Windows Task Scheduler wrappers for warmup tasks"
```

---

## Task 7: sender module (claude -p)

**Files:**
- Create: `warmup/sender.py`
- Test: `tests/test_sender.py`

- [ ] **Step 1: Write the failing test**

`tests/test_sender.py`:
```python
from types import SimpleNamespace

from warmup.sender import SendResult, send_warmup


def _fake_proc(returncode=0, stdout="hello", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_dry_run_does_not_call_runner():
    called = []
    res = send_warmup("ping", "haiku", dry_run=True,
                      runner=lambda *a, **k: called.append(a) or _fake_proc())
    assert res == SendResult(ok=True, detail="dry-run")
    assert called == []


def test_send_warmup_success():
    captured = {}

    def runner(args, **kwargs):
        captured["args"] = args
        return _fake_proc(returncode=0, stdout="ok")

    res = send_warmup("ping", "haiku", dry_run=False, runner=runner, available=lambda: True)
    assert res.ok is True
    assert captured["args"][:3] == ["claude", "-p", "ping"]
    assert "--model" in captured["args"] and "haiku" in captured["args"]


def test_send_warmup_reports_missing_cli():
    res = send_warmup("ping", "haiku", dry_run=False,
                      runner=lambda *a, **k: _fake_proc(), available=lambda: False)
    assert res.ok is False
    assert "not found" in res.detail


def test_send_warmup_nonzero_returncode_is_failure():
    res = send_warmup("ping", "haiku", dry_run=False,
                      runner=lambda *a, **k: _fake_proc(returncode=1, stdout="", stderr="boom"),
                      available=lambda: True)
    assert res.ok is False
    assert "boom" in res.detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sender.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.sender'`

- [ ] **Step 3: Write minimal implementation**

`warmup/sender.py`:
```python
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SendResult:
    ok: bool
    detail: str


def claude_available() -> bool:
    return shutil.which("claude") is not None


def using_api_key() -> bool:
    """Best-effort heuristic: an env API key suggests console billing, not the
    subscription window the warmup relies on."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def send_warmup(
    prompt: str,
    model: str,
    dry_run: bool,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    available: Callable[[], bool] = claude_available,
) -> SendResult:
    if dry_run:
        return SendResult(ok=True, detail="dry-run")
    if not available():
        return SendResult(ok=False, detail="claude CLI not found on PATH")
    proc = runner(
        ["claude", "-p", prompt, "--model", model],
        capture_output=True, text=True, timeout=120,
    )
    detail = (proc.stdout or proc.stderr or "").strip()[:200]
    return SendResult(ok=(proc.returncode == 0), detail=detail)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sender.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add warmup/sender.py tests/test_sender.py
git commit -m "feat: warmup sender via claude -p with dry-run and auth guards"
```

---

## Task 8: monitor module (orchestration)

**Files:**
- Create: `warmup/monitor.py`
- Test: `tests/test_monitor.py`

- [ ] **Step 1: Write the failing test**

`tests/test_monitor.py`:
```python
from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from warmup.config import Config, PeakRule
from warmup.state import State
from warmup.window import WindowState
from warmup.monitor import run_monitor

UTC = timezone.utc


class FakeScheduler:
    def __init__(self):
        self.registered = None
        self.cancelled = False

    def register_ping(self, run_at):
        self.registered = run_at

    def cancel_ping(self):
        self.cancelled = True


def _config(enabled=True):
    # 2026-06-01 is a Monday; peak 14:00-20:00 local.
    return Config(
        enabled=enabled, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(PeakRule(days=("Mon",), start="14:00", end="20:00"),),
    )


def test_monitor_disabled_cancels_ping():
    sched = FakeScheduler()
    state = run_monitor(_config(enabled=False), now=datetime(2026, 6, 1, 8, tzinfo=UTC),
                        records=[], tz=UTC, scheduler=sched, state=State(None, "", None))
    assert sched.cancelled is True
    assert state.next_warmup is None


def test_monitor_idle_schedules_ping():
    sched = FakeScheduler()
    now = datetime(2026, 6, 1, 8, tzinfo=UTC)  # Monday morning, idle
    state = run_monitor(_config(), now=now, records=[], tz=UTC,
                        scheduler=sched, state=State(None, "", None))
    # ideal warmup = 14:00 + 2.5 - 5 = 11:30
    assert sched.registered == datetime(2026, 6, 1, 11, 30, tzinfo=UTC)
    assert state.next_warmup == datetime(2026, 6, 1, 11, 30, tzinfo=UTC)


def test_monitor_no_plan_cancels_ping():
    sched = FakeScheduler()
    # now is after the only peak -> nothing to schedule today; next Monday is >1 day out
    now = datetime(2026, 6, 1, 21, tzinfo=UTC)
    state = run_monitor(_config(), now=now, records=[], tz=UTC,
                        scheduler=sched, state=State(None, "", None))
    assert sched.cancelled is True
    assert state.next_warmup is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_monitor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.monitor'`

- [ ] **Step 3: Write minimal implementation**

`warmup/monitor.py`:
```python
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from warmup.config import Config, peaks_for_date
from warmup.logreader import ActivityRecord
from warmup.planner import plan_day
from warmup.state import State
from warmup.window import current_window


def run_monitor(
    config: Config,
    now: datetime,
    records: list[ActivityRecord],
    tz: ZoneInfo,
    scheduler,
    state: State,
) -> State:
    if not config.enabled:
        scheduler.cancel_ping()
        return replace(state, next_warmup=None)

    window = current_window(records, now)
    today = now.astimezone(tz).date()
    tomorrow = today + timedelta(days=1)
    segments = peaks_for_date(config, today, tz) + peaks_for_date(config, tomorrow, tz)
    plans = plan_day(segments, window, now, config.offset_hours, config.band_minutes)

    if not plans:
        scheduler.cancel_ping()
        return replace(state, next_warmup=None)

    next_warmup = plans[0].time
    scheduler.register_ping(next_warmup)
    return replace(state, next_warmup=next_warmup)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_monitor.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add warmup/monitor.py tests/test_monitor.py
git commit -m "feat: monitor orchestration ties window state to scheduled warmup"
```

---

## Task 9: advisor module

**Files:**
- Create: `warmup/advisor.py`
- Test: `tests/test_advisor.py`

- [ ] **Step 1: Write the failing test**

`tests/test_advisor.py`:
```python
from datetime import datetime, timezone

from warmup.config import Config, PeakRule
from warmup.logreader import ActivityRecord
from warmup.advisor import top_usage_hours, peak_suggestions

UTC = timezone.utc


def _rec(h, tokens):
    return ActivityRecord(datetime(2026, 6, 1, h, tzinfo=UTC), tokens, "x")


def test_top_usage_hours_ranks_by_tokens():
    records = [_rec(9, 100), _rec(9, 50), _rec(15, 500), _rec(21, 10)]
    top = top_usage_hours(records, UTC, n=2)
    assert top == [15, 9]  # 500 then 150


def test_peak_suggestions_flags_uncovered_hot_hour():
    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(PeakRule(days=("Mon",), start="14:00", end="20:00"),),
    )
    # Hour 9 is hot but not inside any configured peak (14-20).
    records = [_rec(9, 1000), _rec(15, 100)]
    msgs = peak_suggestions(records, cfg, UTC)
    assert any("09:00" in m for m in msgs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_advisor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.advisor'`

- [ ] **Step 3: Write minimal implementation**

`warmup/advisor.py`:
```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from warmup.config import Config, WEEKDAYS, _parse_hhmm
from warmup.logreader import ActivityRecord, hourly_histogram


def top_usage_hours(records: list[ActivityRecord], tz: ZoneInfo, n: int) -> list[int]:
    hist = hourly_histogram(records, tz)
    ranked = sorted(hist.items(), key=lambda kv: kv[1], reverse=True)
    return [hour for hour, _ in ranked[:n]]


def _covered_hours(config: Config) -> set[int]:
    hours: set[int] = set()
    for rule in config.peaks:
        start = _parse_hhmm(rule.start).hour
        end = _parse_hhmm(rule.end).hour
        for h in range(start, end):
            hours.add(h)
    return hours


def peak_suggestions(records: list[ActivityRecord], config: Config, tz: ZoneInfo) -> list[str]:
    msgs: list[str] = []
    covered = _covered_hours(config)
    for hour in top_usage_hours(records, tz, n=3):
        if hour not in covered:
            msgs.append(
                f"Heavy usage around {hour:02d}:00 is not inside any configured peak; "
                f"consider adding a peak segment covering it."
            )
    if not msgs:
        msgs.append("Your configured peaks already cover your heaviest-usage hours.")
    return msgs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_advisor.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add warmup/advisor.py tests/test_advisor.py
git commit -m "feat: usage-history advisor suggests peak coverage"
```

---

## Task 10: CLI module

**Files:**
- Create: `warmup/cli.py`
- Test: `tests/test_cli.py`

The CLI resolves shared paths, picks the local timezone, and wires modules. Subcommands: `init`, `monitor`, `ping`, `status`, `advise`. The actual scheduled command for a ping is `"<python>" -m warmup ping`.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from pathlib import Path

from warmup.cli import main
from warmup.config import default_config_toml


def test_init_writes_config_and_example(tmp_path: Path):
    rc = main(["init", "--home", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "config.toml").exists()
    assert "offset_hours" in (tmp_path / "config.toml").read_text(encoding="utf-8")


def test_init_does_not_overwrite_existing(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("# mine\n", encoding="utf-8")
    rc = main(["init", "--home", str(tmp_path)])
    assert rc == 0
    assert cfg.read_text(encoding="utf-8") == "# mine\n"


def test_status_runs_without_config_dir(tmp_path: Path, capsys):
    # No config yet -> status should report not-configured, not crash.
    rc = main(["status", "--home", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "config" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'warmup.cli'`

- [ ] **Step 3: Write minimal implementation**

`warmup/cli.py`:
```python
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from warmup.config import Config, default_config_toml, load_config
from warmup.logreader import read_activity
from warmup.monitor import run_monitor
from warmup.scheduler import Scheduler
from warmup.sender import send_warmup, using_api_key
from warmup.state import State, load_state, save_state
from warmup.window import current_window
from warmup.advisor import peak_suggestions


def _home(args) -> Path:
    return Path(args.home) if args.home else Path.home() / ".claude-warmup"


def _claude_dir() -> Path:
    return Path.home() / ".claude"


def _local_tz() -> ZoneInfo:
    # Use the system local timezone; fall back to UTC.
    local = datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(str(local))
    except Exception:
        return ZoneInfo("UTC")


def _ping_command() -> str:
    return f'"{sys.executable}" -m warmup ping'


def cmd_init(args) -> int:
    home = _home(args)
    home.mkdir(parents=True, exist_ok=True)
    cfg_path = home / "config.toml"
    if cfg_path.exists():
        print(f"config already exists at {cfg_path}; leaving it untouched")
        return 0
    cfg_path.write_text(default_config_toml(), encoding="utf-8")
    print(f"wrote default config to {cfg_path}")
    if using_api_key():
        print("WARNING: ANTHROPIC_API_KEY is set; Claude Code may be on API billing. "
              "Warmup only affects the subscription window.")
    return 0


def _load_or_none(home: Path) -> Config | None:
    cfg_path = home / "config.toml"
    if not cfg_path.exists():
        return None
    return load_config(cfg_path)


def cmd_monitor(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` first")
        return 1
    tz = _local_tz()
    now = datetime.now(timezone.utc)
    records = read_activity(_claude_dir())
    sched = Scheduler(command=_ping_command())
    state = load_state(home / "state.json")
    new_state = run_monitor(cfg, now, records, tz, sched, state)
    save_state(home / "state.json", new_state)
    print(f"next warmup: {new_state.next_warmup}")
    return 0


def cmd_ping(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` first")
        return 1
    now = datetime.now(timezone.utc)
    records = read_activity(_claude_dir())
    window = current_window(records, now)
    state = load_state(home / "state.json")
    if window.active:
        msg = f"skipped: block active until {window.ends_at}"
        print(msg)
        save_state(home / "state.json", State(state.last_warmup, msg, state.next_warmup))
        return 0
    result = send_warmup(cfg.warmup_prompt, cfg.model, cfg.dry_run)
    detail = "ok" if result.ok else f"failed: {result.detail}"
    print(f"warmup {detail}")
    save_state(home / "state.json", State(now, detail, state.next_warmup))
    return 0 if result.ok else 1


def cmd_status(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` to create one")
        return 0
    now = datetime.now(timezone.utc)
    records = read_activity(_claude_dir())
    window = current_window(records, now)
    state = load_state(home / "state.json")
    print(f"window active: {window.active}")
    print(f"block anchor:  {window.anchor}")
    print(f"block ends:    {window.ends_at}")
    print(f"last warmup:   {state.last_warmup} ({state.last_result})")
    print(f"next warmup:   {state.next_warmup}")
    return 0


def cmd_advise(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` first")
        return 1
    tz = _local_tz()
    records = read_activity(_claude_dir())
    for line in peak_suggestions(records, cfg, tz):
        print("- " + line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="warmup")
    parser.add_argument("--home", help="config/state directory (default ~/.claude-warmup)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in [
        ("init", cmd_init), ("monitor", cmd_monitor), ("ping", cmd_ping),
        ("status", cmd_status), ("advise", cmd_advise),
    ]:
        sp = sub.add_parser(name)
        sp.add_argument("--home", help="config/state directory")
        sp.set_defaults(func=fn)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
```

Note: `--home` is declared both on the top parser and each subparser so it works in either position; the subparser value wins when present. `_home` reads `args.home` which argparse sets from whichever was supplied.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS (all tests green)

- [ ] **Step 6: Commit**

```bash
git add warmup/cli.py tests/test_cli.py
git commit -m "feat: CLI wiring for init/monitor/ping/status/advise"
```

---

## Task 11: README, example config, and one-time monitor registration

**Files:**
- Create: `README.md`, `config.example.toml`

- [ ] **Step 1: Write `config.example.toml`**

Reuse the default content. Create `config.example.toml`:
```toml
[warmup]
enabled        = true
offset_hours   = 2.5
band_minutes   = 15
warmup_prompt  = "ping"
model          = "haiku"
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

- [ ] **Step 2: Write `README.md`**

```markdown
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
warmup (default 15).
```

- [ ] **Step 3: Verify the package runs end-to-end (dry run)**

Run:
```bash
python -m warmup init --home .tmp-home
python -m warmup status --home .tmp-home
```
Expected: `init` writes a config; `status` prints window state lines without error.

- [ ] **Step 4: Clean up the temp dir**

```bash
rm -rf .tmp-home
```

- [ ] **Step 5: Commit**

```bash
git add README.md config.example.toml
git commit -m "docs: README and example config with multi-segment peaks"
```

---

## Self-Review Notes

**Spec coverage check:**
- Shared account window / subscription requirement → README + `sender.using_api_key` warning (Tasks 7, 10, 11). ✅
- Warmup math (`peak_start + offset − 5h`) → `planner.ideal_warmup_time` (Task 4). ✅
- Feasibility shift when mid-block → `planner.feasible_warmup_time` (Task 4). ✅
- 15-min monitor, local-only → `monitor.run_monitor` + Task 11 monitor registration. ✅
- ±15-min skip band → `planner.segment_already_covered` (Task 4). ✅
- Multiple peak segments + reset-in-gaps → `planner.plan_day` projected_reset chaining (Task 4). ✅
- Skip ping when block active → `cli.cmd_ping` (Task 10). ✅
- Usage-history advice → `advisor` (Task 9). ✅
- Error handling (missing CLI, dry-run, timezone, idempotent task names) → Tasks 6, 7, 10. ✅
- State/observability → `state` + `status` (Tasks 5, 10). ✅
- Out of scope (API warmup, web automation, non-Windows) → not implemented, by design. ✅

**Note on a known v1 simplification:** `plan_day` projects only forward from the current/most-recent window and the warmups it schedules; it does not model the user doing *unplanned* heavy work between segments. The 15-min monitor compensates by re-running against fresh live state. This matches the spec's "re-evaluated every 15 min against live state."
