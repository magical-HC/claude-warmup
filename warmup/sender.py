from __future__ import annotations

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class SendResult:
    ok: bool
    detail: str


def _vscode_glob_patterns() -> list[str]:
    home = Path.home()
    return [
        str(home / ".vscode" / "extensions" / "anthropic.claude-code-*" / "resources" / "native-binary" / "claude.exe"),
        str(home / ".vscode" / "extensions" / "anthropic.claude-code-*" / "resources" / "native-binary" / "claude"),
    ]


def find_claude(override: str = "") -> str | None:
    """Return the path to the claude CLI executable, or None if not found.

    Resolution order:
    1. override path from config (explicit beats everything)
    2. shutil.which — works when claude is on PATH (npm global install, etc.)
    3. VS Code extension native binary — common on machines that installed
       Claude Code as a VS Code extension rather than a standalone CLI
    """
    if override:
        return str(override) if Path(override).exists() else None

    found = shutil.which("claude")
    if found:
        return found

    for pattern in _vscode_glob_patterns():
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]  # latest version (lexicographic = version order)

    return None


def using_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def send_warmup(
    prompt: str,
    model: str,
    dry_run: bool,
    claude_path: str = "",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    _find: Callable[[], str | None] | None = None,
) -> SendResult:
    if dry_run:
        return SendResult(ok=True, detail="dry-run")
    exe = (_find or (lambda: find_claude(claude_path)))()
    if not exe:
        return SendResult(ok=False, detail="claude CLI not found on PATH or in VS Code extensions")
    proc = runner(
        [exe, "-p", prompt, "--model", model],
        capture_output=True, text=True, timeout=120,
    )
    detail = (proc.stdout or proc.stderr or "").strip()[:200]
    return SendResult(ok=(proc.returncode == 0), detail=detail)
