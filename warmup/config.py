from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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
    timezone: str = ""


def load_config(path: Path) -> Config:
    # utf-8-sig tolerates an optional BOM (e.g. from Notepad); tomllib rejects a
    # BOM if the file is parsed as raw bytes.
    data = tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))
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
        timezone=str(w.get("timezone", "")),
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
        if rule.end == "24:00":
            end = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=tz)
        else:
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
timezone       = ""      # IANA name e.g. "Asia/Shanghai"; empty = system local

[monitor]
interval_minutes = 15

[[peak]]
days  = ["Mon","Tue","Wed","Thu","Fri"]
start = "14:00"
end   = "20:00"
"""
