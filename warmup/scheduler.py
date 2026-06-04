from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime
from typing import Callable
from xml.sax.saxutils import escape

PING_TASK = "ClaudeWarmup-Ping"
MONITOR_TASK = "ClaudeWarmup-Monitor"


class SchedulerError(RuntimeError):
    """Raised when a schtasks command fails."""


def build_task_xml(run_at: datetime, command: str, arguments: str) -> str:
    """Build a Task Scheduler XML definition.

    Uses ISO 8601 for the start time, which is locale-independent — unlike the
    ``/SD`` flag, whose expected date format follows the system locale and breaks
    on non-US machines. The tz-less StartBoundary is interpreted as local time, so
    ``run_at`` is rendered as local wall-clock (any tzinfo is dropped).
    """
    start = run_at.strftime("%Y-%m-%dT%H:%M:%S")
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Description>Claude warmup ping</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <TimeTrigger>\n"
        f"      <StartBoundary>{start}</StartBoundary>\n"
        "      <Enabled>true</Enabled>\n"
        "    </TimeTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <Enabled>true</Enabled>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{escape(command)}</Command>\n"
        f"      <Arguments>{escape(arguments)}</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def build_register_xml_args(task: str, xml_path: str) -> list[str]:
    return ["schtasks", "/Create", "/TN", task, "/XML", xml_path, "/F"]


def build_register_minute_args(task: str, interval_minutes: int, command: str) -> list[str]:
    return [
        "schtasks", "/Create", "/TN", task, "/TR", command,
        "/SC", "MINUTE", "/MO", str(interval_minutes),
        "/F",
    ]


def build_delete_args(task: str) -> list[str]:
    return ["schtasks", "/Delete", "/TN", task, "/F"]


def _default_runner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _check(proc, action: str) -> None:
    """Raise SchedulerError if the schtasks process failed.

    Tolerates ``None`` (test fakes that record args without returning a process).
    """
    if proc is None:
        return
    if getattr(proc, "returncode", 0) != 0:
        detail = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()
        raise SchedulerError(f"{action} failed (exit {proc.returncode}): {detail}")


class Scheduler:
    def __init__(
        self,
        command: str,
        arguments: str,
        runner: Callable[[list[str]], object] = _default_runner,
    ):
        self.command = command
        self.arguments = arguments
        self.runner = runner

    def register_ping(self, run_at: datetime) -> None:
        xml = build_task_xml(run_at, self.command, self.arguments)
        fd, path = tempfile.mkstemp(suffix=".xml")
        try:
            with os.fdopen(fd, "w", encoding="utf-16") as f:
                f.write(xml)
            proc = self.runner(build_register_xml_args(PING_TASK, path))
            _check(proc, "register warmup task")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def cancel_ping(self) -> None:
        # Tolerant: deleting a task that doesn't exist is not an error for us.
        self.runner(build_delete_args(PING_TASK))

    def register_monitor(self, interval_minutes: int, command: str) -> None:
        proc = self.runner(build_register_minute_args(MONITOR_TASK, interval_minutes, command))
        _check(proc, "register monitor task")
