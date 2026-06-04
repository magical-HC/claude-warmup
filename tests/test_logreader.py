from pathlib import Path
from zoneinfo import ZoneInfo

from warmup.logreader import ActivityRecord, read_jsonl_file, hourly_histogram

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


def test_read_jsonl_file_extracts_assistant_usage():
    records = read_jsonl_file(FIXTURE)
    # Only the two assistant records with usage are returned
    assert len(records) == 2
    assert all(isinstance(r, ActivityRecord) for r in records)
    first = records[0]
    assert first.tokens == 150  # 100 + 50
    assert first.model == "claude-haiku-4-5"
    assert first.timestamp.tzinfo is not None
    assert first.timestamp.utcoffset().total_seconds() == 0  # UTC


def test_hourly_histogram_buckets_by_local_hour():
    records = read_jsonl_file(FIXTURE)
    tz = ZoneInfo("UTC")
    hist = hourly_histogram(records, tz)
    # Both records fall in the 18:00 UTC hour
    assert hist[18] == 150 + 280
