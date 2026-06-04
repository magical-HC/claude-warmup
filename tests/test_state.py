from datetime import datetime, timezone
from pathlib import Path

from warmup.state import State, load_state, save_state


def test_roundtrip_state(tmp_path: Path):
    p = tmp_path / "state.json"
    s = State(
        last_warmup=datetime(2026, 6, 1, 11, 30, tzinfo=timezone.utc),
        last_result="ok",
        next_warmup=datetime(2026, 6, 2, 11, 30, tzinfo=timezone.utc),
    )
    save_state(p, s)
    loaded = load_state(p)
    assert loaded == s


def test_load_missing_returns_empty(tmp_path: Path):
    s = load_state(tmp_path / "nope.json")
    assert s == State(last_warmup=None, last_result="", next_warmup=None)
