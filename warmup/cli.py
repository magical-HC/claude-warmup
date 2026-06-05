from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from warmup.config import Config, default_config_toml, load_config
from warmup.wintz import windows_key_to_iana
from warmup.logreader import read_activity
from warmup.monitor import run_monitor
from warmup.scheduler import Scheduler, SchedulerError
from warmup.sender import send_warmup, using_api_key
from warmup.state import State, load_state, save_state
from warmup.window import current_window
from warmup.advisor import peak_suggestions
from warmup.log import append_log


def _home(args) -> Path:
    return Path(args.home) if args.home else Path.home() / ".claude-warmup"


def _claude_dir() -> Path:
    return Path.home() / ".claude"


def _iana_from_local_str() -> ZoneInfo | None:
    """Try to build a ZoneInfo directly from the local tzinfo string (works on POSIX
    where str(tzinfo) is already an IANA name like 'Asia/Shanghai')."""
    try:
        return ZoneInfo(str(datetime.now().astimezone().tzinfo))
    except Exception:
        return None


def _windows_tz_key() -> str | None:
    """Read the English Windows timezone key from the registry (always English
    regardless of display locale, e.g. 'China Standard Time')."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        )
        name = winreg.QueryValueEx(key, "TimeZoneKeyName")[0]
        winreg.CloseKey(key)
        return name
    except Exception:
        return None


def _resolve_tz(config) -> ZoneInfo:
    if config.timezone:
        return ZoneInfo(config.timezone)

    # Works on POSIX (Linux/Mac) where str(tzinfo) is already an IANA name.
    tz = _iana_from_local_str()
    if tz is not None:
        return tz

    # Windows: registry key is always the English name regardless of display locale.
    win_key = _windows_tz_key()
    if win_key:
        iana = windows_key_to_iana(win_key)
        if iana:
            return ZoneInfo(iana)

    # Last resort: warn and fall back to UTC.
    name = datetime.now().astimezone().tzname()
    print(
        f"WARNING: could not resolve local timezone '{name}'; falling back to UTC. "
        'Set `timezone` in config.toml to an IANA name (e.g. "Asia/Shanghai").',
        file=sys.stderr,
    )
    return ZoneInfo("UTC")


def _fmt(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return "(none)"
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")


def _delta(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return ""
    secs = int((dt - now).total_seconds())
    if secs < 0:
        return " (past)"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f" (in {h}h {m:02d}m)" if h else f" (in {m}m)"


_W = 48  # status box width


def _row(label: str, value: str) -> str:
    return f"  {label:<12}{value}"


def _rule() -> str:
    return "-" * _W


def _header(title: str) -> str:
    return f"{'=' * _W}\n  {title}\n{'=' * _W}"


def _ping_scheduler() -> Scheduler:
    return Scheduler(command=sys.executable, arguments="-m warmup ping")


def cmd_init(args) -> int:
    home = _home(args)
    home.mkdir(parents=True, exist_ok=True)
    cfg_path = home / "config.toml"
    if cfg_path.exists():
        print(f"config already exists at {cfg_path}; leaving it untouched")
        return 0
    cfg_path.write_text(default_config_toml(), encoding="utf-8")
    print(f"wrote default config to {cfg_path}")
    if using_api_key():
        print("WARNING: ANTHROPIC_API_KEY is set; Claude Code may be on API billing. "
              "Warmup only affects the subscription window.")
    return 0


def _load_or_none(home: Path) -> Config | None:
    cfg_path = home / "config.toml"
    if not cfg_path.exists():
        return None
    return load_config(cfg_path)


def cmd_monitor(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` first")
        return 1
    tz = _resolve_tz(cfg)
    now = datetime.now(timezone.utc)
    records = read_activity(_claude_dir())
    sched = _ping_scheduler()
    state = load_state(home / "state.json")
    log = home / "warmup.log"
    try:
        new_state = run_monitor(cfg, now, records, tz, sched, state)
    except SchedulerError as e:
        append_log(log, f"monitor  ERROR: {e}")
        print(f"ERROR: failed to schedule warmup: {e}", file=sys.stderr)
        return 1
    next_str = _fmt(new_state.next_warmup, tz) if new_state.next_warmup else "none"
    append_log(log, f"monitor  next={next_str}")
    save_state(home / "state.json", new_state)
    print(f"next warmup: {_fmt(new_state.next_warmup, tz)}")
    return 0


def cmd_ping(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` first")
        return 1
    tz = _resolve_tz(cfg)
    now = datetime.now(timezone.utc)
    records = read_activity(_claude_dir())
    window = current_window(records, now)
    state = load_state(home / "state.json")
    test_mode = getattr(args, "test", False)
    if window.active and not test_mode:
        msg = f"skipped: block active until {_fmt(window.ends_at, tz)}"
        print(msg)
        save_state(home / "state.json", State(state.last_warmup, msg, state.next_warmup, state.paused))
        return 0
    if test_mode:
        print(f"[test] sending ping (ignoring active block)...")
    result = send_warmup(cfg.warmup_prompt, cfg.model, cfg.dry_run, cfg.claude_path)
    detail = "ok" if result.ok else f"failed: {result.detail}"
    print(f"warmup {detail}")
    save_state(home / "state.json", State(now, detail, state.next_warmup, state.paused))
    return 0 if result.ok else 1


def cmd_pause(args) -> int:
    home = _home(args)
    state = load_state(home / "state.json")
    if state.paused:
        print("monitor is already paused  (run 'warmup resume' to re-enable)")
        return 0
    sched = _ping_scheduler()
    sched.cancel_ping()
    from dataclasses import replace as dc_replace
    save_state(home / "state.json", dc_replace(state, paused=True, next_warmup=None))
    append_log(home / "warmup.log", "paused   monitor disabled by user")
    print("monitor paused  (run 'warmup resume' to re-enable)")
    return 0


def cmd_resume(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` first")
        return 1
    state = load_state(home / "state.json")
    if not state.paused:
        print("monitor is already running")
        return 0
    from dataclasses import replace as dc_replace
    save_state(home / "state.json", dc_replace(state, paused=False))
    append_log(home / "warmup.log", "resumed  monitor re-enabled by user")
    print("monitor resumed, rescheduling...")
    return cmd_monitor(args)


def cmd_status(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` to create one")
        return 0
    tz = _resolve_tz(cfg)
    now = datetime.now(timezone.utc)
    records = read_activity(_claude_dir())
    window = current_window(records, now)
    state = load_state(home / "state.json")

    out: list[str] = [_header("claude-warmup"), ""]

    # ── 5-hour window section ────────────────────────────────────────────────
    out.append(_row("5h window", "ACTIVE" if window.active else "inactive"))
    out.append(_row("  opened",  _fmt(window.anchor, tz)))
    expires_str = _fmt(window.ends_at, tz)
    if window.active:
        expires_str += _delta(window.ends_at, now)
    out.append(_row("  expires", expires_str))

    out.append("")
    out.append(_rule())
    out.append("")

    # ── monitor section ──────────────────────────────────────────────────────
    monitor_status = "PAUSED" if state.paused else "RUNNING"
    out.append(_row("monitor", monitor_status))
    next_str = _fmt(state.next_warmup, tz)
    if state.next_warmup and not state.paused:
        next_str += _delta(state.next_warmup, now)
    out.append(_row("  next ping", next_str))
    last_str = _fmt(state.last_warmup, tz)
    if state.last_result:
        last_str += f"  [{state.last_result}]"
    out.append(_row("  last ping", last_str))

    out.append("")
    out.append("=" * _W)
    print("\n".join(out))
    return 0


def cmd_advise(args) -> int:
    home = _home(args)
    cfg = _load_or_none(home)
    if cfg is None:
        print("no config found; run `warmup init` first")
        return 1
    tz = _resolve_tz(cfg)
    records = read_activity(_claude_dir())
    for line in peak_suggestions(records, cfg, tz):
        print("- " + line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="warmup")
    parser.add_argument("--home", help="config/state directory (default ~/.claude-warmup)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in [
        ("init", cmd_init), ("monitor", cmd_monitor), ("ping", cmd_ping),
        ("status", cmd_status), ("advise", cmd_advise),
        ("pause", cmd_pause), ("resume", cmd_resume),
    ]:
        sp = sub.add_parser(name)
        sp.add_argument("--home", default=argparse.SUPPRESS, help="config/state directory")
        if name == "ping":
            sp.add_argument("--test", action="store_true",
                            help="send ping immediately, bypassing block-active check")
        sp.set_defaults(func=fn)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
