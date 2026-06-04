from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from warmup.config import Config, default_config_toml, load_config
from warmup.logreader import read_activity
from warmup.monitor import run_monitor
from warmup.scheduler import Scheduler, SchedulerError
from warmup.sender import send_warmup, using_api_key
from warmup.state import State, load_state, save_state
from warmup.window import current_window
from warmup.advisor import peak_suggestions


def _home(args) -> Path:
    return Path(args.home) if args.home else Path.home() / ".claude-warmup"


def _claude_dir() -> Path:
    return Path.home() / ".claude"


def _resolve_tz(config) -> ZoneInfo:
    if config.timezone:
        return ZoneInfo(config.timezone)
    name = datetime.now().astimezone().tzname()
    try:
        return ZoneInfo(str(datetime.now().astimezone().tzinfo))
    except Exception:
        print(
            f"WARNING: could not resolve local timezone '{name}'; falling back to UTC. "
            "Set `timezone` in config.toml to an IANA name (e.g. \"Asia/Shanghai\").",
            file=sys.stderr,
        )
        return ZoneInfo("UTC")


def _fmt(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")


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
    try:
        new_state = run_monitor(cfg, now, records, tz, sched, state)
    except SchedulerError as e:
        print(f"ERROR: failed to schedule warmup: {e}", file=sys.stderr)
        return 1
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
    if window.active:
        msg = f"skipped: block active until {_fmt(window.ends_at, tz)}"
        print(msg)
        save_state(home / "state.json", State(state.last_warmup, msg, state.next_warmup))
        return 0
    result = send_warmup(cfg.warmup_prompt, cfg.model, cfg.dry_run)
    detail = "ok" if result.ok else f"failed: {result.detail}"
    print(f"warmup {detail}")
    save_state(home / "state.json", State(now, detail, state.next_warmup))
    return 0 if result.ok else 1


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
    print(f"window active: {window.active}")
    print(f"block anchor:  {_fmt(window.anchor, tz)}")
    print(f"block ends:    {_fmt(window.ends_at, tz)}")
    print(f"last warmup:   {_fmt(state.last_warmup, tz)} ({state.last_result})")
    print(f"next warmup:   {_fmt(state.next_warmup, tz)}")
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
    ]:
        sp = sub.add_parser(name)
        sp.add_argument("--home", default=argparse.SUPPRESS, help="config/state directory")
        sp.set_defaults(func=fn)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
