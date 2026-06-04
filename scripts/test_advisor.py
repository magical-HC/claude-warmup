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


def test_covered_hours_wraps_cross_midnight():
    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(PeakRule(days=("Mon",), start="20:00", end="01:00"),),
    )
    # Hours 20,21,22,23,0 should be covered; 1 should not (end is exclusive)
    records = [_rec(22, 500), _rec(9, 400), _rec(1, 300), _rec(0, 200)]
    msgs = peak_suggestions(records, cfg, UTC)
    # hour 9 and hour 1 are not covered
    assert any("09:00" in m for m in msgs)
    assert any("01:00" in m for m in msgs)
    # hours 22 and 0 are covered — no suggestion for them
    assert not any("22:00" in m for m in msgs)
    assert not any("00:00" in m for m in msgs)


def test_peak_suggestions_handles_end_24():
    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(PeakRule(days=("Mon",), start="19:00", end="24:00"),),
    )
    # Hours 19-23 are covered; hour 9 is not.
    records = [_rec(9, 1000), _rec(21, 100)]
    msgs = peak_suggestions(records, cfg, UTC)
    assert any("09:00" in m for m in msgs)
    # 21:00 is inside the peak (19-24), so no suggestion for it
    assert not any("21:00" in m for m in msgs)


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
