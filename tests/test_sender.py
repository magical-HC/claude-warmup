from types import SimpleNamespace

from warmup.sender import SendResult, send_warmup


def _fake_proc(returncode=0, stdout="hello", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_dry_run_does_not_call_runner():
    called = []
    res = send_warmup("ping", "haiku", dry_run=True,
                      runner=lambda *a, **k: called.append(a) or _fake_proc())
    assert res == SendResult(ok=True, detail="dry-run")
    assert called == []


def test_send_warmup_success():
    captured = {}

    def runner(args, **kwargs):
        captured["args"] = args
        return _fake_proc(returncode=0, stdout="ok")

    res = send_warmup("ping", "haiku", dry_run=False, runner=runner, available=lambda: True)
    assert res.ok is True
    assert captured["args"][:3] == ["claude", "-p", "ping"]
    assert "--model" in captured["args"] and "haiku" in captured["args"]


def test_send_warmup_reports_missing_cli():
    res = send_warmup("ping", "haiku", dry_run=False,
                      runner=lambda *a, **k: _fake_proc(), available=lambda: False)
    assert res.ok is False
    assert "not found" in res.detail


def test_send_warmup_nonzero_returncode_is_failure():
    res = send_warmup("ping", "haiku", dry_run=False,
                      runner=lambda *a, **k: _fake_proc(returncode=1, stdout="", stderr="boom"),
                      available=lambda: True)
    assert res.ok is False
    assert "boom" in res.detail
