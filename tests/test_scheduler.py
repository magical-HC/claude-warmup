from datetime import datetime, timezone

from warmup.scheduler import (
    PING_TASK,
    MONITOR_TASK,
    build_register_once_args,
    build_register_minute_args,
    build_delete_args,
    Scheduler,
)


def test_build_register_once_args():
    run_at = datetime(2026, 6, 1, 11, 30, tzinfo=timezone.utc)
    args = build_register_once_args(PING_TASK, run_at, "cmd here")
    assert args[:4] == ["schtasks", "/Create", "/TN", PING_TASK]
    assert "/SC" in args and "ONCE" in args
    assert "11:30" in args
    assert "06/01/2026" in args
    assert args[-1] == "/F"


def test_build_register_minute_args():
    args = build_register_minute_args(MONITOR_TASK, 15, "cmd here")
    assert "MINUTE" in args
    assert "/MO" in args and "15" in args


def test_build_delete_args():
    assert build_delete_args(PING_TASK) == ["schtasks", "/Delete", "/TN", PING_TASK, "/F"]


def test_scheduler_register_ping_invokes_runner():
    calls = []
    sched = Scheduler(command="my-cmd", runner=lambda args: calls.append(args))
    sched.register_ping(datetime(2026, 6, 1, 11, 30, tzinfo=timezone.utc))
    assert len(calls) == 1
    assert calls[0][:2] == ["schtasks", "/Create"]
    assert "my-cmd" in calls[0]


def test_scheduler_cancel_ping_invokes_delete():
    calls = []
    sched = Scheduler(command="my-cmd", runner=lambda args: calls.append(args))
    sched.cancel_ping()
    assert calls == [["schtasks", "/Delete", "/TN", PING_TASK, "/F"]]
