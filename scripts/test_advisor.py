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
