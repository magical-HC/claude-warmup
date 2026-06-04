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
