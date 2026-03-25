import argparse
import urllib.error

from scripts.ops import run_runtime_model_refresh as refresh


def _args(**overrides):
    base = {
        "failure_webhook_url": "",
        "failure_webhook_timeout_s": 1.0,
        "failure_notify_command": "",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_maybe_emit_failure_alert_noop_when_gate_passed(monkeypatch):
    calls = {"webhook": 0, "notify": 0}

    monkeypatch.setattr(
        refresh,
        "_send_failure_webhook",
        lambda **kwargs: calls.__setitem__("webhook", calls["webhook"] + 1),
    )
    monkeypatch.setattr(
        refresh,
        "_run_failure_command",
        lambda **kwargs: calls.__setitem__("notify", calls["notify"] + 1),
    )

    alerts = refresh._maybe_emit_failure_alert(
        args=_args(
            failure_webhook_url="https://example.com/hook",
            failure_notify_command="echo fail",
        ),
        context={"gate_passed": True, "reason": "refresh_gate_passed"},
    )

    assert calls["webhook"] == 0
    assert calls["notify"] == 0
    assert alerts["webhook"]["attempted"] is False
    assert alerts["notify_command"]["attempted"] is False


def test_maybe_emit_failure_alert_triggers_webhook_and_notify(monkeypatch):
    webhook_payload = {}
    notify_payload = {}

    def _fake_webhook(**kwargs):
        webhook_payload.update(kwargs)
        return {"attempted": True, "sent": True, "status_code": 200, "error": None}

    def _fake_notify(**kwargs):
        notify_payload.update(kwargs)
        return {"attempted": True, "returncode": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(refresh, "_send_failure_webhook", _fake_webhook)
    monkeypatch.setattr(refresh, "_run_failure_command", _fake_notify)

    context = {
        "gate_passed": False,
        "reason": "refresh_gate_blocked",
        "refresh_report_json": "/tmp/report.json",
    }
    alerts = refresh._maybe_emit_failure_alert(
        args=_args(
            failure_webhook_url="https://example.com/hook",
            failure_webhook_timeout_s=2.5,
            failure_notify_command="echo fail",
        ),
        context=context,
    )

    assert alerts["webhook"]["attempted"] is True
    assert alerts["notify_command"]["attempted"] is True
    assert webhook_payload["webhook_url"] == "https://example.com/hook"
    assert webhook_payload["timeout_s"] == 2.5
    assert webhook_payload["payload"]["reason"] == "refresh_gate_blocked"
    assert notify_payload["command"] == "echo fail"
    assert notify_payload["context"]["refresh_report_json"] == "/tmp/report.json"


def test_send_failure_webhook_handles_url_error(monkeypatch):
    def _raise_url_error(*args, **kwargs):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(refresh.urllib.request, "urlopen", _raise_url_error)

    result = refresh._send_failure_webhook(
        webhook_url="https://example.com/hook",
        payload={"reason": "refresh_gate_blocked"},
        timeout_s=1.0,
    )

    assert result["attempted"] is True
    assert result["sent"] is False
    assert result["status_code"] is None
    assert "network down" in (result["error"] or "")


def test_run_failure_command_injects_runtime_context(monkeypatch):
    recorded = {}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(command, **kwargs):
        recorded["command"] = command
        recorded["env"] = kwargs.get("env", {})
        return _Proc()

    monkeypatch.setattr(refresh.subprocess, "run", _fake_run)

    result = refresh._run_failure_command(
        command="echo fail",
        context={
            "reason": "refresh_runtime_exception",
            "refresh_report_json": "/tmp/r.json",
            "gate_passed": False,
        },
    )

    assert result["attempted"] is True
    assert result["returncode"] == 0
    assert recorded["command"] == "echo fail"
    assert recorded["env"]["RUNTIME_REFRESH_REASON"] == "refresh_runtime_exception"
    assert recorded["env"]["RUNTIME_REFRESH_REPORT"] == "/tmp/r.json"
    assert recorded["env"]["RUNTIME_REFRESH_GATE_PASSED"] == "0"
