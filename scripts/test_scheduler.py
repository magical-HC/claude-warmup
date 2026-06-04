from datetime import datetime, timezone

import pytest

from warmup.scheduler import (
    PING_TASK,
    MONITOR_TASK,
    SchedulerError,
    build_task_xml,
    build_register_xml_args,
    build_register_minute_args,
    build_delete_args,
    Scheduler,
)


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_build_task_xml_uses_iso_local_datetime():
    # Locale-independent: ISO 8601, NOT the locale's date format.
    xml = build_task_xml(datetime(2026, 6, 5, 11, 30), r"C:\py.exe", "-m warmup ping")
    assert "<StartBoundary>2026-06-05T11:30:00</StartBoundary>" in xml
    assert r"<Command>C:\py.exe</Command>" in xml
    assert "<Arguments>-m warmup ping</Arguments>" in xml


def test_build_task_xml_drops_tzinfo_to_local_wallclock():
    # An aware datetime is rendered as local wall-clock time (Task Scheduler
    # interprets a tz-less StartBoundary as local time).
    aware = datetime(2026, 6, 5, 11, 30, tzinfo=timezone.utc)
    xml = build_task_xml(aware, "py", "-m warmup ping")
    assert "<StartBoundary>2026-06-05T11:30:00</StartBoundary>" in xml


def test_build_register_xml_args():
    assert build_register_xml_args(PING_TASK, r"C:\x.xml") == [
        "schtasks", "/Create", "/TN", PING_TASK, "/XML", r"C:\x.xml", "/F",
    ]


def test_build_register_minute_args():
    args = build_register_minute_args(MONITOR_TASK, 15, "cmd here")
    assert "MINUTE" in args
    assert "/MO" in args and "15" in args


def test_build_delete_args():
    assert build_delete_args(PING_TASK) == ["schtasks", "/Delete", "/TN", PING_TASK, "/F"]


def test_register_ping_passes_xml_path_to_runner():
    captured = {}

    def runner(args):
        captured["args"] = args
        return _FakeProc(returncode=0)

    sched = Scheduler(command="py", arguments="-m warmup ping", runner=runner)
    sched.register_ping(datetime(2026, 6, 5, 11, 30))
    assert captured["args"][:4] == ["schtasks", "/Create", "/TN", PING_TASK]
    assert "/XML" in captured["args"]


def test_register_ping_raises_on_schtasks_failure():
    # This is the bug that hid behind silent failure: a non-zero schtasks exit
    # must surface, not be swallowed.
    def runner(args):
        return _FakeProc(returncode=1, stderr="ERROR: Invalid Start Date")

    sched = Scheduler(command="py", arguments="-m warmup ping", runner=runner)
    with pytest.raises(SchedulerError) as exc:
        sched.register_ping(datetime(2026, 6, 5, 11, 30))
    assert "Invalid Start Date" in str(exc.value)


def test_cancel_ping_is_tolerant_of_failure():
    # Deleting a task that does not exist must NOT raise.
    calls = []

    def runner(args):
        calls.append(args)
        return _FakeProc(returncode=1, stderr="ERROR: cannot find the file")

    sched = Scheduler(command="py", arguments="-m warmup ping", runner=runner)
    sched.cancel_ping()  # no exception
    assert calls == [["schtasks", "/Delete", "/TN", PING_TASK, "/F"]]
