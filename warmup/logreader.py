from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ActivityRecord:
    timestamp: datetime  # tz-aware UTC
    tokens: int
    model: str


def _parse_ts(s: str) -> datetime:
    # Logs use trailing 'Z'; normalize to +00:00 for fromisoformat.
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def read_jsonl_file(path: Path) -> list[ActivityRecord]:
    records: list[ActivityRecord] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            ts = d.get("timestamp")
            if not isinstance(usage, dict) or not ts:
                continue
            tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
            records.append(ActivityRecord(_parse_ts(ts), tokens, str(msg.get("model", "unknown"))))
    return records


def read_activity(claude_dir: Path) -> list[ActivityRecord]:
    records: list[ActivityRecord] = []
    for path in (claude_dir / "projects").rglob("*.jsonl"):
        records.extend(read_jsonl_file(path))
    records.sort(key=lambda r: r.timestamp)
    return records


def hourly_histogram(records: list[ActivityRecord], tz: ZoneInfo) -> dict[int, int]:
    hist: dict[int, int] = {}
    for r in records:
        hour = r.timestamp.astimezone(tz).hour
        hist[hour] = hist.get(hour, 0) + r.tokens
    return hist
