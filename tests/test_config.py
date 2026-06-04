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
