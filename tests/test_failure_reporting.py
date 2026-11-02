"""Private diagnostics, durable recovery and mocked GitHub publication."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_vav_preflight import sdk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/sdk_scripts"))
from common import failure_reporting as reporting


@pytest.fixture
def event():
    return {
        "operation": "remove_hvac",
        "stage": "apply",
        "provider": "sdk",
        "category": "plan_nondeterminism",
        "exception_type": "RuntimeError",
        "actual": "Saved validation failed for Confidential Building; token=secret123 at /Users/person/private/model.osm https://internal.example/building",
        "expected": "The reviewed plan and repeated SDK loads agree.",
        "command": [
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
            "execute_python_script",
            "/plugin/sdk/remove_hvac.py",
            "--plan",
            "/Users/person/plan.json",
        ],
        "environment": {
            "required_sdk": "3.11.0",
            "bundle_id": "b" * 64,
            "host": "claude",
            "username": "person",
        },
        "settings": {
            "name": "Confidential Building",
            "pressure_rise_pa": 650,
            "password": "do-not-upload",
            "heating": {"type": "water"},
        },
        "model_context": {
            "object_counts": {"OS_AirLoopHVAC": 2},
            "source_sha256": "a" * 64,
            "full_model": "private dump",
        },
        "private_values": ["Confidential Building"],
        "transcript": "private conversation",
    }


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.created = []
        self.offline = False
        self.ambiguous = False
        self.index_delayed = False
        self.templates = None

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        if self.offline:
            raise reporting.TransportError("offline")
        if endpoint.startswith("search/issues?"):
            return {
                "items": [] if self.index_delayed else self.created,
                "incomplete_results": False,
            }
        if endpoint.endswith("contents/.github/ISSUE_TEMPLATE"):
            return self.templates
        assert (
            method == "POST" and endpoint == "repos/pnnl/openstudio-ai-harness/issues"
        )
        issue = dict(number=1, html_url=reporting.ISSUE_ROOT + "1", **payload)
        self.created.append(issue)
        if self.ambiguous:
            raise reporting.TransportError("timeout_after_creation")
        return issue

    @property
    def posts(self):
        return [x for x in self.calls if x[0] == "POST"]


def test_allowlist_redacts_private_data_and_preserves_settings(event):
    public = reporting.sanitize(event)
    encoded = json.dumps(public)
    for private in [
        "Confidential",
        "secret123",
        "/Users/",
        "internal.example",
        "do-not-upload",
        "private dump",
        "private conversation",
        "person",
        "username",
        "password",
    ]:
        assert private not in encoded
    assert public["settings"]["pressure_rise_pa"] == 650
    assert public["settings"]["heating"]["type"] == "water"
    assert public["model_context"]["object_counts"] == {"OS_AirLoopHVAC": 2}
    assert public["command"][0] == "openstudio"
    assert public["reproducer"]["status"] == "not_independently_reproducible_yet"
    assert len(encoded) < 12000


def test_input_schema_fields_and_fixed_options_survive_diagnostic_filter():
    fields, literals = set(), set()

    def visit(value):
        if isinstance(value, dict):
            fields.update(value.get("properties", {}))
            literals.update(x for x in value.get("enum", []) if isinstance(x, str))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for schema in (ROOT / "skills/sdk_scripts/references").glob("*.schema.json"):
        visit(json.loads(schema.read_text()))
    assert fields <= reporting.CONFIG_KEYS
    assert literals <= reporting.SAFE_WORDS
    values = {
        "central_heating": {"type": "Water"},
        "target_zones": [{"name": "private zone"}],
        "fan_total_efficiency": 0.7,
        "zone": {"name": "Acme Tower 123 Private Road contact@example.com"},
        "terminal": {"name": "Acme Tower East Terminal"},
        "settings": {
            "damper_heating_action": "ReverseWithLimits",
            "maximum_reheat_temperature_c": 30,
        },
    }
    safe = reporting.sanitize({"settings": values})["settings"]
    assert safe["central_heating"]["type"] == "Water"
    assert safe["target_zones"][0]["name"].startswith("<value-")
    assert safe["settings"]["damper_heating_action"] == "ReverseWithLimits"
    assert safe["settings"]["maximum_reheat_temperature_c"] == 30
    assert "Acme" not in json.dumps(safe) and "contact@example.com" not in json.dumps(
        safe
    )


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_abcdef123456789",
        "github_pat_private_token",
        "Authorization: Bearer hidden-token",
        "api_key=hidden-value",
        "password:two word hidden-value",
        "C:\\Users\\secret\\file.osm",
        "person@example.com",
        "https://intranet.example/private",
        '"Private Zone"',
    ],
)
def test_unstructured_log_redaction(secret):
    sanitized = reporting.Sanitizer().text(secret)
    assert secret not in sanitized
    assert "hidden-token" not in sanitized and "hidden-value" not in sanitized


def test_submission_writes_exact_draft_and_receipt_before_post(event, tmp_path):
    captured = reporting.capture(event, tmp_path)
    receipt = Path(captured["receipt"])
    transport = FakeGitHub()
    original = transport.request

    def request(method, endpoint, payload=None):
        if method == "POST":
            assert reporting.read_json(receipt)["status"] == "submitting"
            assert reporting.read_json(receipt.parent / "issue.json") == payload
        return original(method, endpoint, payload)

    transport.request = request
    result = reporting.submit(receipt, tmp_path, transport)
    assert result["status"] == "submitted"
    assert result["issue"]["url"] == reporting.ISSUE_ROOT + "1"
    assert len(transport.posts) == 1
    body = transport.posts[0][2]["body"]
    assert "not_independently_reproducible_yet" in body
    assert "Confidential" not in body and "secret123" not in body


def test_same_failure_and_workaround_do_not_duplicate_issue(event, tmp_path):
    first = reporting.capture(event, tmp_path)
    transport = FakeGitHub()
    reporting.submit(first["receipt"], tmp_path, transport)
    event["workarounds"] = [
        "Bundled preparation completed; original failure still recorded."
    ]
    second = reporting.capture(event, tmp_path)
    assert first["fingerprint"] == second["fingerprint"]
    reporting.submit(second["receipt"], tmp_path, transport)
    assert len(transport.posts) == 1
    assert reporting.read_json(first["receipt"])["public"]["actual"]


def test_remote_duplicate_links_closed_or_open_issue_without_edit(event, tmp_path):
    captured = reporting.capture(event, tmp_path)
    transport = FakeGitHub()
    transport.created = [
        {
            "number": 7,
            "html_url": reporting.ISSUE_ROOT + "7",
            "body": f"<!-- openstudio-ai-incident:{captured['fingerprint']} -->",
            "state": "closed",
        }
    ]
    result = reporting.submit(captured["receipt"], tmp_path, transport)
    assert result["status"] == "duplicate" and not transport.posts
    assert result["issue"]["number"] == 7


@pytest.mark.parametrize("delayed", [False, True])
def test_ambiguous_creation_checks_marker_and_never_posts_twice(
    event, tmp_path, delayed
):
    captured = reporting.capture(event, tmp_path)
    transport = FakeGitHub()
    transport.ambiguous = True
    transport.index_delayed = delayed
    first = reporting.submit(captured["receipt"], tmp_path, transport)
    assert first["status"] == ("submission_uncertain" if delayed else "submitted")
    second = reporting.submit(captured["receipt"], tmp_path, transport)
    assert second["status"] == first["status"]
    assert len(transport.posts) == 1
    transport.index_delayed = False
    result = reporting.submit(captured["receipt"], tmp_path, transport)
    assert result["status"] in {"duplicate", "submitted"}
    assert len(transport.posts) == 1


def test_offline_retains_copy_ready_draft_and_later_submits(event, tmp_path):
    captured = reporting.capture(event, tmp_path)
    transport = FakeGitHub()
    transport.offline = True
    assert (
        reporting.submit(captured["receipt"], tmp_path, transport)["status"]
        == "pending"
    )
    assert Path(captured["receipt"]).with_name("issue.json").is_file()
    transport.offline = False
    assert (
        reporting.submit(captured["receipt"], tmp_path, transport)["status"]
        == "submitted"
    )
    assert len(transport.posts) == 1


@pytest.mark.parametrize("mode", ["disabled", "security"])
def test_disabled_and_security_incidents_never_contact_github(event, tmp_path, mode):
    if mode == "disabled":
        reporting.write_json(tmp_path / "policy.json", {"mode": "disabled"})
    else:
        event["security_sensitive"] = True
    captured = reporting.capture(event, tmp_path)
    transport = FakeGitHub()
    result = reporting.submit(captured["receipt"], tmp_path, transport)
    assert result["status"] in {"disabled", "local_only"}
    assert transport.calls == []


def test_security_classification_can_hold_an_existing_pending_receipt(event, tmp_path):
    first = reporting.capture(event, tmp_path)
    event["security_sensitive"] = True
    second = reporting.capture(event, tmp_path)
    assert second["fingerprint"] == first["fingerprint"]
    transport = FakeGitHub()
    assert (
        reporting.submit(second["receipt"], tmp_path, transport)["status"]
        == "local_only"
    )
    assert not transport.calls


def test_unknown_repository_template_is_not_bypassed(event, tmp_path):
    captured = reporting.capture(event, tmp_path)
    transport = FakeGitHub()
    transport.templates = [{"name": "bug.yml"}]
    result = reporting.submit(captured["receipt"], tmp_path, transport)
    assert result["status"] == "pending"
    assert result["reason"] == "repository_template_requires_mapping"
    assert not transport.posts


def test_current_markdown_bug_template_populates_sections_and_required_labels(
    event, tmp_path
):
    import base64

    captured = reporting.capture(event, tmp_path)
    transport = FakeGitHub()
    transport.templates = [{"name": "bug_report.md"}]
    original = transport.request
    template = "---\nname: Bug report\nabout: Report a failure\ntitle: ''\nlabels: bug\nassignees: ''\n---\n## Describe the bug\n## To Reproduce\n## Expected behavior\n## Environment\n## Additional context\n"

    def request(method, endpoint, payload=None):
        if endpoint.endswith("/bug_report.md"):
            return {
                "encoding": "base64",
                "content": base64.b64encode(template.encode()).decode(),
            }
        return original(method, endpoint, payload)

    transport.request = request
    result = reporting.submit(captured["receipt"], tmp_path, transport)
    assert result["status"] == "submitted"
    payload = transport.posts[0][2]
    assert payload["labels"] == ["bug"]
    assert "## Describe the bug" in payload["body"]
    assert "## Environment" in payload["body"] and "3.11.0" in payload["body"]
    assert (
        reporting.read_json(Path(captured["receipt"]).with_name("issue.json"))
        == payload
    )


def test_capture_and_pending_work_without_site_packages_or_sdk(event, tmp_path):
    source = tmp_path / "event.json"
    source.write_text(json.dumps(event))
    script = ROOT / "skills/sdk_scripts/common/failure_reporting.py"
    command = [
        sys.executable,
        "-I",
        "-S",
        str(script),
        "--state-dir",
        str(tmp_path / "state"),
    ]
    run = subprocess.run(
        command + ["capture", "--event", str(source)], capture_output=True, text=True
    )
    assert run.returncode == 0, run.stdout + run.stderr
    captured = json.loads(run.stdout)
    run = subprocess.run(command + ["pending"], capture_output=True, text=True)
    assert json.loads(run.stdout)["pending"][0]["receipt"] == captured["receipt"]


def test_unexpected_sdk_exception_preserves_numeric_config_and_receipt(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENSTUDIO_AI_FAILURE_DIR", str(tmp_path / "incidents"))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"name": "Private Building", "pressure_rise_pa": 650}))
    result = reporting.capture_exception(
        RuntimeError("SDK rejected Private Building"),
        "remove_hvac",
        "apply",
        SimpleNamespace(config=config),
    )
    record = reporting.read_json(result["failure_receipt"])
    assert record["public"]["settings"]["pressure_rise_pa"] == 650
    assert "Private Building" not in json.dumps(record)


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Missing selection"),
        FileNotFoundError("No file"),
        PermissionError("No permission"),
    ],
)
def test_expected_errors_do_not_create_incidents(error, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSTUDIO_AI_FAILURE_DIR", str(tmp_path))
    assert reporting.capture_exception(error, "remove_hvac", "preflight") == {}
    assert list(tmp_path.iterdir()) == []


def test_lock_and_tampered_identity_prevent_external_mutation(event, tmp_path):
    captured = reporting.capture(event, tmp_path)
    receipt = Path(captured["receipt"])
    lock = receipt.with_name("submission.lock")
    lock.touch()
    transport = FakeGitHub()
    assert reporting.submit(receipt, tmp_path, transport)["status"] == "busy"
    lock.unlink()
    record = reporting.read_json(receipt)
    record["public"]["actual"] = "Tampered signature"
    reporting.write_json(receipt, record)
    with pytest.raises(ValueError, match="identity changed"):
        reporting.submit(receipt, tmp_path, transport)
    assert transport.calls == []


def test_reporter_failure_cannot_replace_model_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        reporting, "capture", lambda *a: (_ for _ in ()).throw(OSError("disk full"))
    )
    assert reporting.capture_exception(
        RuntimeError("SDK failure"), "remove_hvac", "apply"
    ) == {"failure_capture_unavailable": True}


def test_synthetic_reproduction_is_explicit_and_survives_submission(event, tmp_path):
    event["reproducer"] = {
        "synthetic_verified": True,
        "steps": [
            "Create two AirLoopHVAC objects in a model.",
            "Inject a RuntimeError during the removal planner; verify a local receipt precedes recovery.",
        ],
    }
    captured = reporting.capture(event, tmp_path)
    transport = FakeGitHub()
    reporting.submit(captured["receipt"], tmp_path, transport)
    assert "synthetic_steps_verified" in transport.posts[0][2]["body"]


def test_shared_cli_captures_failure_before_report_and_keeps_original_error(
    tmp_path, monkeypatch, capsys
):
    from common import model_transaction as tx

    monkeypatch.setenv("OPENSTUDIO_AI_FAILURE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(tx, "require_sdk", lambda: object())
    monkeypatch.setattr(
        tx, "load_model", lambda *a: (object(), SimpleNamespace(warnings=lambda: []))
    )
    source = tmp_path / "model.osm"
    source.write_text("source bytes unchanged")
    destination = tmp_path / "failed.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["remove_hvac.py", "--input", str(source), "--report", str(destination)],
    )

    def inventory(model):
        raise RuntimeError("SDK inventory fault")

    assert tx.cli("remove_hvac", None, None, None, inventory) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "SDK inventory fault"
    assert Path(output["failure_receipt"]).is_file()
    assert (
        json.loads(destination.read_text())["failure_receipt"]
        == output["failure_receipt"]
    )
    assert source.read_text() == "source bytes unchanged"


@pytest.mark.parametrize("error_kind", ["preparation", "stale", "invalid_model"])
def test_preparation_and_stale_model_diagnostics_do_not_submit(
    error_kind, tmp_path, monkeypatch
):
    from common.diagnostics import DiagnosticError, mismatch
    from common.version_guard import PreparationRequired

    errors = {
        "preparation": PreparationRequired(
            "Upgrade first", status="requires_preparation"
        ),
        "stale": mismatch({"input_sha256": "a"}, {"input_sha256": "b"}),
        "invalid_model": DiagnosticError("Missing list", status="invalid_model"),
    }
    monkeypatch.setenv("OPENSTUDIO_AI_FAILURE_DIR", str(tmp_path))
    assert (
        reporting.capture_exception(errors[error_kind], "remove_hvac", "preflight")
        == {}
    )
    assert not list(tmp_path.glob("*/receipt.json"))


def test_handle_churn_is_captured_and_aliased(tmp_path, monkeypatch):
    from common.diagnostics import mismatch

    monkeypatch.setenv("OPENSTUDIO_AI_FAILURE_DIR", str(tmp_path))
    error = mismatch(
        {"handle": "{11111111-1111-1111-1111-111111111111}"},
        {"handle": "{22222222-2222-2222-2222-222222222222}"},
    )
    result = reporting.capture_exception(error, "remove_hvac", "apply")
    assert Path(result["failure_receipt"]).is_file()
    public = reporting.read_json(result["failure_receipt"])["public"]
    assert public["diagnostic"]["differences"] == [
        {"path": "/handle", "category": "handle_churn"}
    ]
    assert "11111111-1111" not in json.dumps(public)


def test_optional_reporting_readiness_does_not_gate_modeling(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting.shutil, "which", lambda _: None)
    result = reporting.readiness(tmp_path)
    assert not result["submission_ready"] and result["optional"]
    assert result["affects_modeling_readiness"] is False
    assert result["submission_account"] == reporting.SUBMISSION_ACCOUNT


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_reporter_survives_missing_shared_sdk_and_relocation(event, tmp_path, host):
    import shutil
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=ROOT, runtime_mode="marketplace"
        )
    )
    result = adapter.export_plugin(tmp_path / "export", dry_run=False)
    moved = tmp_path / "moved plugin"
    shutil.move(str(result.plugin_dir), moved)
    shutil.rmtree(moved / "sdk")
    state = tmp_path / "state"
    source = tmp_path / "event.json"
    source.write_text(json.dumps(event))
    script = moved / "skills/report-openstudio-failure/scripts/report_failure.py"
    command = [sys.executable, "-I", "-S", str(script), "--state-dir", str(state)]
    run = subprocess.run(
        command + ["capture", "--event", str(source)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    receipt = json.loads(run.stdout)["receipt"]
    assert Path(receipt).is_file()
    # Disable publication, then exercise the complete command without network.
    run = subprocess.run(
        command + ["policy", "disabled"], capture_output=True, text=True
    )
    assert run.returncode == 0
    run = subprocess.run(
        command + ["submit", "--receipt", receipt], capture_output=True, text=True
    )
    assert json.loads(run.stdout)["status"] == "disabled"
    policy = (
        (moved / "agents/openstudio-modeler.md")
        if host == "claude"
        else (moved / "skills/openstudio-modeling-orchestrator/SKILL.md")
    )
    assert "report-openstudio-failure" in policy.read_text()
    assert "automatic" in policy.read_text()
    assert (
        "report-openstudio-failure"
        in (moved / "skills/openstudio-hvac-remover/SKILL.md").read_text()
    )
    account = "Issues are created under your own authenticated GitHub account."
    for document in (
        moved / "README.md",
        moved / "skills/setup-openstudio-ai/SKILL.md",
        moved / "skills/doctor-openstudio-ai/SKILL.md",
        moved / "skills/report-openstudio-failure/SKILL.md",
        (
            result.plugin_dir.parent / "INSTALL.md"
            if host == "claude"
            else result.plugin_dir.parents[1] / "INSTALL.md"
        ),
    ):
        assert account in document.read_text(), document


def test_github_transport_uses_fixed_host_json_stdin_and_bounded_errors(monkeypatch):
    monkeypatch.setattr(reporting.shutil, "which", lambda _: "/tools/gh")

    def run(command, **kwargs):
        assert command[:6] == [
            "/tools/gh",
            "api",
            "--hostname",
            "github.com",
            "--method",
            "POST",
        ]
        assert command[-2:] == ["--input", "-"]
        assert json.loads(kwargs["input"]) == {"title": "test", "body": "safe"}
        assert kwargs["timeout"] == 20
        return SimpleNamespace(returncode=1, stdout="", stderr="PRIVATE AUTH TOKEN")

    monkeypatch.setattr(reporting.subprocess, "run", run)
    with pytest.raises(reporting.TransportError) as error:
        reporting.GitHub().request(
            "POST",
            "repos/pnnl/openstudio-ai-harness/issues",
            {"title": "test", "body": "safe"},
        )
    assert str(error.value) == "github_request_failed"
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_native_public_remover_failure_saves_receipt_and_preserves_source(
    tmp_path, host
):
    import hashlib
    import os
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    cli = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not cli.is_file():
        pytest.skip("Native 3.11.0 CLI unavailable")
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=ROOT, runtime_mode="marketplace"
        )
    )
    plugin = adapter.export_plugin(tmp_path / "export", dry_run=False).plugin_dir
    source = tmp_path / "synthetic.osm"
    report = tmp_path / "failure.json"
    before = tmp_path / "source.sha256"
    launcher = plugin / "skills/openstudio-hvac-remover/scripts/remove_hvac.py"
    driver = tmp_path / "inject_fault.py"
    driver.write_text(
        "import hashlib, runpy, sys\nfrom pathlib import Path\nimport openstudio\n"
        "model=openstudio.model.Model()\n"
        "openstudio.model.AirLoopHVAC(model)\nopenstudio.model.AirLoopHVAC(model)\n"
        f"model.save({str(source)!r}, True)\n"
        f"Path({str(before)!r}).write_text(hashlib.sha256(Path({str(source)!r}).read_bytes()).hexdigest())\n"
        f"sys.path.insert(0, {str(plugin / 'sdk')!r})\n"
        "import common.hvac_remove as remover\n"
        "def fault(*args):\n    raise RuntimeError('Synthetic SDK inventory fault')\n"
        "remover.inventory=fault\n"
        f"sys.argv=[{str(launcher)!r}, '--input', {str(source)!r}, '--report', {str(report)!r}]\n"
        f"runpy.run_path({str(launcher)!r}, run_name='__main__')\n"
    )
    env = os.environ.copy()
    env["OPENSTUDIO_AI_FAILURE_DIR"] = str(tmp_path / "incidents")
    run = subprocess.run(
        [str(cli), "execute_python_script", str(driver)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert run.returncode == 2, run.stdout + run.stderr
    failed = reporting.read_json(report)
    assert failed["error"] == "Synthetic SDK inventory fault"
    receipt = reporting.read_json(failed["failure_receipt"])
    assert receipt["public"]["environment"]["required_sdk"] == "3.11.0"
    assert receipt["public"]["environment"]["observed_sdk"].split("+")[0] == "3.11.0"
    assert receipt["public"]["environment"]["source_version"] == "3.11.0"
    assert receipt["public"]["environment"]["bundle_id"]
    assert receipt["public"]["environment"]["plugin_version"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before.read_text()


def test_large_valid_configuration_has_bounded_receipt_and_explicit_gap(
    event, tmp_path
):
    value = {key: 1 for key in sorted(reporting.CONFIG_KEYS)[:60]}
    event["settings"] = {
        "air_loops": [
            {"controls": value, "sizing": value, "fan": value} for _ in range(12)
        ]
    }
    result = reporting.capture(event, tmp_path)
    receipt = Path(result["receipt"])
    record = reporting.read_json(receipt)
    assert receipt.stat().st_size < reporting.MAX_INPUT
    assert record["public"]["settings"] == {}
    assert "size limit" in json.dumps(record["public"]["observations"])
    transport = FakeGitHub()
    assert reporting.submit(receipt, tmp_path, transport)["status"] == "submitted"
    assert len(transport.posts[0][2]["body"]) < 50000


def test_reporter_and_sdk_capture_share_environment_selected_policy(tmp_path):
    import os

    state = tmp_path / "shared state"
    reporting.write_json(state / "policy.json", {"mode": "disabled"})
    env = os.environ.copy()
    env["OPENSTUDIO_AI_FAILURE_DIR"] = str(state)
    env["PATH"] = ""
    script = ROOT / "skills/sdk_scripts/common/failure_reporting.py"
    run = subprocess.run(
        [sys.executable, "-I", "-S", str(script), "doctor"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)["mode"] == "disabled"


@pytest.mark.parametrize("mode", ["inspect_only", "edit_model"])
def test_report_failure_distinguishes_read_only_from_published_output(
    tmp_path, monkeypatch, mode
):
    monkeypatch.setenv("OPENSTUDIO_AI_FAILURE_DIR", str(tmp_path))
    error = (
        PermissionError("report destination denied")
        if mode == "edit_model"
        else RuntimeError("report write failed")
    )
    result = reporting.capture_exception(
        error, "remove_hvac", "report", report={"ok": True, "mode": mode}
    )
    record = reporting.read_json(result["failure_receipt"])
    text = record["public"]["publication"]
    if mode == "edit_model":
        assert text.startswith("published;") and "do not repeat" in text
    else:
        assert text.startswith("unpublished;")


@pytest.fixture
def confidential_model(sdk, tmp_path):
    """Synthetic SDK fixture; no user model, config/private_values or regex hints."""
    native = sdk[0]
    values = ["Acme Tower Level 3 AHU Riser B", "123 Cedar Avenue", "ops@acme.example"]
    name = " | ".join(values)
    model = native.model.Model()
    zone = native.model.ThermalZone(model)
    zone.setName(name)
    unattached = native.model.CoilHeatingWater(model)
    unattached.setName(name)
    attached = native.model.CoilHeatingWater(model)
    attached.setName("Central water coil")
    source = native.model.PlantLoop(model)
    target = native.model.PlantLoop(model)
    assert source.addDemandBranchForComponent(attached)
    air = native.model.AirLoopHVAC(model)
    assert attached.addToNode(air.supplyOutletNode())
    path = tmp_path / "confidential.osm"
    assert model.save(str(path), True)
    return SimpleNamespace(
        native=native,
        model=model,
        zone=zone,
        unattached=unattached,
        attached=attached,
        source=source,
        target=target,
        path=path,
        values=values,
    )


@pytest.mark.parametrize(
    "path",
    ["sdk_setter", "plant_checked", "plant_fields", "water_controller", "migration"],
)
def test_model_values_stay_local_across_real_bundled_error_paths(
    confidential_model, tmp_path, path
):
    import hashlib
    import traceback
    from common import hvac_equipment, plant_create, coil_migration
    from common.coil_equipment import node_ports
    from common.water_coil import ref

    fixture = confidential_model
    before = hashlib.sha256(fixture.path.read_bytes()).hexdigest()
    # Only the setter's failure result is injected; name lookup and the raising
    # function are the real bundled paths, using names from the synthetic OSM.
    rejected = SimpleNamespace(
        nameString=fixture.zone.nameString,
        reject=lambda: False,
        setRejected=lambda value: False,
    )
    with pytest.raises((RuntimeError, ValueError)) as caught:
        if path == "sdk_setter":
            hvac_equipment.call(rejected, "reject")
        elif path == "plant_checked":
            plant_create.checked(rejected, "reject")
        elif path == "plant_fields":
            plant_create.set_fields(rejected, {"Rejected": 1})
        elif path == "water_controller":
            hvac_equipment.water_controller(fixture.unattached, True, {})
        else:
            preview = fixture.native.model.Model(fixture.model.clone(True))
            preview.getThermalZone(fixture.zone.handle()).get().setMultiplier(2)
            planned = {
                "resolved_objects": {
                    "coil": ref(fixture.attached),
                    "controller": ref(fixture.attached.controllerWaterCoil().get()),
                    "source_plant_loop": ref(fixture.source),
                    "plant_loop": ref(fixture.target),
                    "ports": node_ports(fixture.attached),
                },
                "protection": {},
            }
            coil_migration.projection(fixture.model, preview, fixture.native, planned)
    error = caught.value
    for private in fixture.values:
        assert private in str(error)  # Ensure this path actually exercises the leak.
    captured = reporting.capture(
        {
            "operation": "connect_water_coil",
            "stage": "apply",
            "provider": "sdk",
            "exception_type": type(error).__name__,
            "actual": str(error),
            "traceback": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            ),
            "plugin_frames": reporting.exception_frames(error),
        },
        tmp_path / "state",
    )
    receipt = Path(captured["receipt"])
    record = reporting.read_json(receipt)
    public = record["public"]
    assert public["actual"] == reporting.ERROR_MESSAGES[public["error_code"]]
    assert public["traceback"]
    for frame in public["traceback"]:
        assert set(frame) == {"file", "function", "line"}
        assert (ROOT / "skills/sdk_scripts" / frame["file"]).is_file()
        assert isinstance(frame["line"], int)
    private = reporting.read_json(receipt.with_name("private.json"))
    assert private["actual"] == str(error)
    assert private["traceback"]
    if sys.platform != "win32":
        assert receipt.with_name("private.json").stat().st_mode & 0o077 == 0
    transport = FakeGitHub()
    assert (
        reporting.submit(receipt, tmp_path / "state", transport)["status"]
        == "submitted"
    )
    for value in fixture.values:
        for content in (
            json.dumps(record),
            json.dumps(transport.posts[0][2]),
            receipt.with_name("issue.json").read_text(),
        ):
            assert value not in content
    assert hashlib.sha256(fixture.path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "message",
    [
        "Unexpected migration side effect on Acme Tower Level 3 AHU Riser B",
        "SDK rejected Acme Tower Level 3 AHU Riser B.setName",
        "Unrecognised failure in Acme Tower Level 3 AHU Riser B",
    ],
)
def test_exception_capture_does_not_depend_on_private_name_hints(
    message, tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENSTUDIO_AI_FAILURE_DIR", str(tmp_path))
    result = reporting.capture_exception(RuntimeError(message), "remove_hvac", "apply")
    receipt = Path(result["failure_receipt"])
    public = reporting.read_json(receipt)["public"]
    assert "Acme" not in json.dumps(public)
    assert public["traceback"] == []
    assert reporting.read_json(receipt.with_name("private.json"))["actual"] == message


def test_untrusted_tracebacks_cannot_publish_external_frames_or_source_lines(event):
    event["traceback"] = (
        "Acme Tower Level 3 AHU Riser B at 123 Cedar Avenue ops@acme.example"
    )
    event["plugin_frames"] = [
        {"file": "common/hvac_equipment.py", "function": "Acme_Tower", "line": 10},
        {"file": "../../customer.py", "function": "call", "line": 10},
        {"file": "common/hvac_equipment.py", "function": "call", "line": 100000},
        {
            "file": "common/hvac_equipment.py",
            "function": "call",
            "line": 10,
            "source": event["traceback"],
        },
    ]
    public = reporting.sanitize(event)
    assert public["traceback"] == [
        {"file": "common/hvac_equipment.py", "function": "call", "line": 10}
    ]
    assert "Acme" not in json.dumps(public)
    assert reporting.sanitize(public) == public
    event["plugin_frames"] *= 20
    assert len(reporting.sanitize(event)["traceback"]) <= 12


@pytest.mark.parametrize(
    "status", ["pending", "submitted", "submitting", "submission_uncertain"]
)
def test_legacy_receipts_are_never_uploaded_or_reposted(event, tmp_path, status):
    captured = reporting.capture(event, tmp_path)
    receipt = Path(captured["receipt"])
    record = reporting.read_json(receipt)
    record.update(schema_version=1, status=status)
    record["public"][
        "actual"
    ] = "Unexpected migration side effect on Acme Tower Level 3 AHU Riser B"
    reporting.write_json(receipt, record)
    transport = FakeGitHub()
    result = reporting.submit(receipt, tmp_path, transport)
    assert result["status"] == "requires_recapture" and not result["submitted"]
    assert transport.calls == []
    assert reporting.read_json(receipt) == record


def test_reporter_can_publish_safe_receipt_after_sdk_sources_are_lost(
    event, tmp_path, monkeypatch
):
    event["plugin_frames"] = [
        {"file": "common/hvac_equipment.py", "function": "call", "line": 10}
    ]
    captured = reporting.capture(event, tmp_path / "state")
    receipt = Path(captured["receipt"])
    assert reporting.read_json(receipt)["public"]["traceback"]
    monkeypatch.setattr(reporting, "sdk_root", lambda: tmp_path / "missing sdk")
    transport = FakeGitHub()
    assert (
        reporting.submit(receipt, tmp_path / "state", transport)["status"]
        == "submitted"
    )
    public = reporting.read_json(receipt)["public"]
    assert public["traceback"] == []
    assert reporting.fingerprint(public) == captured["fingerprint"]


def test_fixed_error_templates_still_distinguish_plugin_failure_locations(event):
    event["actual"] = "Unrecognised failure in Acme Tower Level 3 AHU Riser B"
    event["plugin_frames"] = [
        {"file": "common/hvac_equipment.py", "function": "call", "line": 10}
    ]
    first = reporting.sanitize(event)
    event["plugin_frames"] = [
        {"file": "common/plant_create.py", "function": "checked", "line": 16}
    ]
    second = reporting.sanitize(event)
    assert first["actual"] == second["actual"]
    assert first["error_site"] != second["error_site"]
    assert reporting.fingerprint(first) != reporting.fingerprint(second)
