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
