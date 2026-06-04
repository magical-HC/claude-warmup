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
