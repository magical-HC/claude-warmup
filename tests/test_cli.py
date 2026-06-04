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
