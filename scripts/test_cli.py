from pathlib import Path

from warmup.cli import main
from warmup.config import default_config_toml


def test_init_writes_config_and_example(tmp_path: Path):
    rc = main(["init", "--home", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "config.toml").exists()
    assert "offset_hours" in (tmp_path / "config.toml").read_text(encoding="utf-8")


def test_init_does_not_overwrite_existing(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("# mine\n", encoding="utf-8")
    rc = main(["init", "--home", str(tmp_path)])
    assert rc == 0
    assert cfg.read_text(encoding="utf-8") == "# mine\n"


def test_status_runs_without_config_dir(tmp_path: Path, capsys):
    # No config yet -> status should report not-configured, not crash.
    rc = main(["status", "--home", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "config" in out.lower()


def test_home_before_subcommand_is_respected(tmp_path: Path):
    rc = main(["--home", str(tmp_path), "init"])
    assert rc == 0
    assert (tmp_path / "config.toml").exists()


def test_resolve_tz_falls_back_via_windows_registry(monkeypatch):
    """When str(tzinfo) isn't a valid IANA name (any non-English Windows locale),
    _resolve_tz must auto-resolve via the Windows registry + CLDR map — no warning,
    no UTC fallback."""
    import warmup.cli as cli
    from zoneinfo import ZoneInfo
    from warmup.config import Config, PeakRule

    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(), timezone="",
    )
    # Simulate a zh-CN Windows: str(tzinfo) returns a localized name that ZoneInfo
    # can't parse, but the registry key is always the English "China Standard Time".
    monkeypatch.setattr(cli, "_windows_tz_key", lambda: "China Standard Time")
    monkeypatch.setattr(cli, "_iana_from_local_str", lambda: None)  # simulate IANA parse failure
    assert cli._resolve_tz(cfg) == ZoneInfo("Asia/Shanghai")


def test_resolve_tz_warns_and_falls_back_to_utc_only_when_unresolvable(monkeypatch, capsys):
    import warmup.cli as cli
    from zoneinfo import ZoneInfo
    from warmup.config import Config

    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(), timezone="",
    )
    monkeypatch.setattr(cli, "_iana_from_local_str", lambda: None)
    monkeypatch.setattr(cli, "_windows_tz_key", lambda: None)   # registry also unavailable
    result = cli._resolve_tz(cfg)
    assert result == ZoneInfo("UTC")
    assert "WARNING" in capsys.readouterr().err


def test_resolve_tz_uses_config_timezone():
    from zoneinfo import ZoneInfo
    from warmup.cli import _resolve_tz
    from warmup.config import Config, PeakRule
    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(PeakRule(days=("Mon",), start="14:00", end="20:00"),),
        timezone="Asia/Shanghai",
    )
    assert _resolve_tz(cfg) == ZoneInfo("Asia/Shanghai")


def test_status_displays_times_in_user_timezone(tmp_path: Path, monkeypatch, capsys):
    from datetime import datetime, timezone as tz
    from zoneinfo import ZoneInfo
    import warmup.cli as cli
    from warmup.window import WindowState

    # Patch config timezone to Asia/Shanghai (+08:00)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        default_config_toml().replace('timezone       = ""', 'timezone       = "Asia/Shanghai"'),
        encoding="utf-8",
    )
    anchor_utc = datetime(2026, 6, 4, 3, 30, tzinfo=tz.utc)  # = 11:30 +08:00
    ends_utc   = datetime(2026, 6, 4, 8, 30, tzinfo=tz.utc)  # = 16:30 +08:00
    monkeypatch.setattr(cli, "current_window", lambda *a, **k: WindowState(True, anchor_utc, ends_utc))
    monkeypatch.setattr(cli, "read_activity", lambda *a: [])

    main(["status", "--home", str(tmp_path)])
    out = capsys.readouterr().out
    # Times must appear in Shanghai local time, not UTC (+00:00)
    assert "+00:00" not in out
    assert "11:30" in out  # anchor in local time
    assert "16:30" in out  # ends_at in local time


def test_ping_skip_message_uses_user_timezone(tmp_path: Path, monkeypatch, capsys):
    from datetime import datetime, timezone as tz
    from zoneinfo import ZoneInfo
    import warmup.cli as cli
    from warmup.window import WindowState

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        default_config_toml().replace('timezone       = ""', 'timezone       = "Asia/Shanghai"'),
        encoding="utf-8",
    )
    ends_utc = datetime(2026, 6, 4, 8, 30, tzinfo=tz.utc)  # = 16:30 +08:00
    monkeypatch.setattr(cli, "current_window", lambda *a, **k: WindowState(True, None, ends_utc))
    monkeypatch.setattr(cli, "read_activity", lambda *a: [])
    monkeypatch.setattr(cli, "save_state", lambda *a, **k: None)

    main(["ping", "--home", str(tmp_path)])
    out = capsys.readouterr().out
    assert "+00:00" not in out
    assert "16:30" in out


def test_monitor_writes_log(tmp_path: Path, monkeypatch, capsys):
    import warmup.cli as cli
    from warmup.window import WindowState

    main(["init", "--home", str(tmp_path)])
    monkeypatch.setattr(cli, "read_activity", lambda *a: [])
    monkeypatch.setattr(cli, "current_window",
                        lambda *a, **k: WindowState(False, None, None))
    monkeypatch.setattr(cli, "_ping_scheduler", lambda: type("S", (), {
        "register_ping": lambda self, t: None,
        "cancel_ping": lambda self: None,
    })())

    main(["monitor", "--home", str(tmp_path)])

    log_path = tmp_path / "warmup.log"
    assert log_path.exists(), "log file should be created on monitor run"
    content = log_path.read_text(encoding="utf-8")
    assert "monitor" in content.lower()


def test_status_shows_recent_log(tmp_path: Path, monkeypatch, capsys):
    import warmup.cli as cli
    from warmup.window import WindowState
    from warmup.log import append_log

    main(["init", "--home", str(tmp_path)])
    append_log(tmp_path / "warmup.log", "monitor  window=inactive  next=none")
    monkeypatch.setattr(cli, "read_activity", lambda *a: [])
    monkeypatch.setattr(cli, "current_window",
                        lambda *a, **k: WindowState(False, None, None))

    main(["status", "--home", str(tmp_path)])
    out = capsys.readouterr().out
    assert "monitor" in out.lower()


def test_pause_sets_paused_in_state(tmp_path: Path, monkeypatch):
    import warmup.cli as cli
    main(["init", "--home", str(tmp_path)])
    monkeypatch.setattr(cli, "_ping_scheduler", lambda: type("S", (), {
        "cancel_ping": lambda self: None})())
    rc = main(["pause", "--home", str(tmp_path)])
    assert rc == 0
    from warmup.state import load_state
    assert load_state(tmp_path / "state.json").paused is True


def test_resume_clears_paused_in_state(tmp_path: Path, monkeypatch):
    import warmup.cli as cli
    from warmup.state import State, save_state
    main(["init", "--home", str(tmp_path)])
    save_state(tmp_path / "state.json", State(None, "", None, paused=True))
    monkeypatch.setattr(cli, "read_activity", lambda *a: [])
    monkeypatch.setattr(cli, "_ping_scheduler", lambda: type("S", (), {
        "register_ping": lambda self, t: None,
        "cancel_ping": lambda self: None})())
    rc = main(["resume", "--home", str(tmp_path)])
    assert rc == 0
    from warmup.state import load_state
    assert load_state(tmp_path / "state.json").paused is False


def test_status_shows_paused(tmp_path: Path, monkeypatch, capsys):
    import warmup.cli as cli
    from warmup.state import State, save_state
    from warmup.window import WindowState
    main(["init", "--home", str(tmp_path)])
    save_state(tmp_path / "state.json", State(None, "", None, paused=True))
    monkeypatch.setattr(cli, "read_activity", lambda *a: [])
    monkeypatch.setattr(cli, "current_window",
                        lambda *a, **k: WindowState(False, None, None))
    main(["status", "--home", str(tmp_path)])
    out = capsys.readouterr().out
    assert "paused" in out.lower()


def test_status_shows_running_when_not_paused(tmp_path: Path, monkeypatch, capsys):
    import warmup.cli as cli
    from warmup.window import WindowState
    main(["init", "--home", str(tmp_path)])
    monkeypatch.setattr(cli, "read_activity", lambda *a: [])
    monkeypatch.setattr(cli, "current_window",
                        lambda *a, **k: WindowState(False, None, None))
    main(["status", "--home", str(tmp_path)])
    out = capsys.readouterr().out
    assert "running" in out.lower()


def test_status_output_has_sections(tmp_path: Path, monkeypatch, capsys):
    import warmup.cli as cli
    from warmup.window import WindowState
    main(["init", "--home", str(tmp_path)])
    monkeypatch.setattr(cli, "read_activity", lambda *a: [])
    monkeypatch.setattr(cli, "current_window",
                        lambda *a, **k: WindowState(False, None, None))
    main(["status", "--home", str(tmp_path)])
    out = capsys.readouterr().out
    assert "window" in out.lower()
    assert "monitor" in out.lower()


def test_cmd_monitor_reports_scheduler_error(tmp_path: Path, monkeypatch, capsys):
    # If schtasks registration fails, monitor must report it and return non-zero,
    # NOT silently claim success.
    import warmup.cli as cli
    from warmup.scheduler import SchedulerError

    main(["init", "--home", str(tmp_path)])

    def boom(*a, **k):
        raise SchedulerError("register warmup task failed (exit 1): bad date")

    monkeypatch.setattr(cli, "run_monitor", boom)
    rc = main(["monitor", "--home", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "failed" in err.lower()
