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
