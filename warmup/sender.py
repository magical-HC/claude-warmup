from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SendResult:
    ok: bool
    detail: str


def claude_available() -> bool:
    return shutil.which("claude") is not None


def using_api_key() -> bool:
    """Best-effort heuristic: an env API key suggests console billing, not the
    subscription window the warmup relies on."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def send_warmup(
    prompt: str,
    model: str,
    dry_run: bool,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    available: Callable[[], bool] = claude_available,
) -> SendResult:
    if dry_run:
        return SendResult(ok=True, detail="dry-run")
    if not available():
        return SendResult(ok=False, detail="claude CLI not found on PATH")
    proc = runner(
        ["claude", "-p", prompt, "--model", model],
        capture_output=True, text=True, timeout=120,
    )
    detail = (proc.stdout or proc.stderr or "").strip()[:200]
    return SendResult(ok=(proc.returncode == 0), detail=detail)
