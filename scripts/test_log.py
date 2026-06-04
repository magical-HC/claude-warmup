from datetime import datetime, timezone
from pathlib import Path

from warmup.log import append_log, read_log


def test_append_creates_file_and_writes_line(tmp_path: Path):
    p = tmp_path / "warmup.log"
    append_log(p, "monitor started")
    assert p.exists()
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "monitor started" in lines[0]
    # line must start with an ISO timestamp
    assert lines[0][0:4].isdigit()


def test_append_multiple_lines(tmp_path: Path):
    p = tmp_path / "warmup.log"
    append_log(p, "first")
    append_log(p, "second")
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "first" in lines[0]
    assert "second" in lines[1]


def test_read_log_returns_last_n(tmp_path: Path):
    p = tmp_path / "warmup.log"
    for i in range(10):
        append_log(p, f"line {i}")
    last = read_log(p, n=3)
    assert len(last) == 3
    assert "line 9" in last[-1]
    assert "line 7" in last[0]


def test_read_log_missing_file_returns_empty(tmp_path: Path):
    assert read_log(tmp_path / "nope.log", n=5) == []
