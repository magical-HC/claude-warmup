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
