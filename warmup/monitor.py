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
