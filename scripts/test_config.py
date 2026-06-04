from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from warmup.config import Config, PeakRule, load_config, default_config_toml, peaks_for_date


def test_load_config_parses_fields(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(default_config_toml(), encoding="utf-8")
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.enabled is True
    assert cfg.offset_hours == 2.5
    assert cfg.band_minutes == 15
    assert cfg.monitor_interval_minutes == 15
    assert cfg.model == "haiku"
    assert any("Mon" in r.days for r in cfg.peaks)


def test_load_config_reads_timezone(tmp_path):
    from pathlib import Path
    p = tmp_path / "config.toml"
    p.write_text(default_config_toml(), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.timezone == ""


def test_load_config_tolerates_utf8_bom(tmp_path: Path):
    # Editors like Notepad add a UTF-8 BOM; tomllib rejects it. We must not crash.
    p = tmp_path / "config.toml"
    p.write_bytes(b"\xef\xbb\xbf" + default_config_toml().encode("utf-8"))
    cfg = load_config(p)
    assert cfg.offset_hours == 2.5
    assert any("Mon" in r.days for r in cfg.peaks)


def test_peaks_for_date_handles_end_24():
    # "24:00" is valid notation for midnight (end of day); it must not crash
    # and the resulting end datetime must be the next day at 00:00.
    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(PeakRule(days=("Mon",), start="19:00", end="24:00"),),
    )
    tz = ZoneInfo("Asia/Shanghai")
    from datetime import date
    segs = peaks_for_date(cfg, date(2026, 6, 1), tz)  # Monday
    assert len(segs) == 1
    start, end = segs[0]
    assert start.hour == 19
    # end should be 2026-06-02 00:00 (next day midnight)
    assert end.day == 2 and end.hour == 0 and end.minute == 0


def test_peaks_for_date_filters_by_weekday():
    cfg = Config(
        enabled=True, offset_hours=2.5, band_minutes=15, warmup_prompt="ping",
        model="haiku", dry_run=False, monitor_interval_minutes=15,
        peaks=(PeakRule(days=("Mon",), start="14:00", end="20:00"),),
    )
    tz = ZoneInfo("America/New_York")
    # 2026-06-01 is a Monday
    segs = peaks_for_date(cfg, datetime(2026, 6, 1, tzinfo=tz).date(), tz)
    assert len(segs) == 1
    start, end = segs[0]
    assert start.hour == 14 and end.hour == 20
    assert start.tzinfo == tz
    # 2026-06-02 is a Tuesday -> no segments
    assert peaks_for_date(cfg, datetime(2026, 6, 2, tzinfo=tz).date(), tz) == []
