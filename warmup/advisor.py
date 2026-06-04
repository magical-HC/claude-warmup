from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from warmup.config import Config, _parse_hhmm
from warmup.logreader import ActivityRecord, hourly_histogram


def top_usage_hours(records: list[ActivityRecord], tz: ZoneInfo, n: int) -> list[int]:
    hist = hourly_histogram(records, tz)
    ranked = sorted(hist.items(), key=lambda kv: kv[1], reverse=True)
    return [hour for hour, _ in ranked[:n]]


def _covered_hours(config: Config) -> set[int]:
    hours: set[int] = set()
    for rule in config.peaks:
        start = _parse_hhmm(rule.start).hour
        end = 24 if rule.end == "24:00" else _parse_hhmm(rule.end).hour
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
