from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Callable

PING_TASK = "ClaudeWarmup-Ping"
MONITOR_TASK = "ClaudeWarmup-Monitor"


def build_register_once_args(task: str, run_at: datetime, command: str) -> list[str]:
    return [
        "schtasks", "/Create", "/TN", task, "/TR", command,
        "/SC", "ONCE",
        "/ST", run_at.strftime("%H:%M"),
        "/SD", run_at.strftime("%m/%d/%Y"),
        "/F",
    ]


def build_register_minute_args(task: str, interval_minutes: int, command: str) -> list[str]:
    return [
        "schtasks", "/Create", "/TN", task, "/TR", command,
        "/SC", "MINUTE", "/MO", str(interval_minutes),
        "/F",
    ]


def build_delete_args(task: str) -> list[str]:
    return ["schtasks", "/Delete", "/TN", task, "/F"]


def _default_runner(args: list[str]) -> None:
    subprocess.run(args, capture_output=True, text=True, check=False)


class Scheduler:
    def __init__(self, command: str, runner: Callable[[list[str]], None] = _default_runner):
        self.command = command
        self.runner = runner

    def register_ping(self, run_at: datetime) -> None:
        self.runner(build_register_once_args(PING_TASK, run_at, self.command))

    def cancel_ping(self) -> None:
        self.runner(build_delete_args(PING_TASK))

    def register_monitor(self, interval_minutes: int, command: str) -> None:
        self.runner(build_register_minute_args(MONITOR_TASK, interval_minutes, command))
