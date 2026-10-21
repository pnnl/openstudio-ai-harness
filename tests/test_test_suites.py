"""Guard the publishing/full-CI boundary against accidental loss of coverage."""

import ast
from pathlib import Path

import pytest
import yaml

from conftest import SLOW_MODULES, SLOW_TESTS, is_slow_test

ROOT = Path(__file__).resolve().parents[1]


def test_slow_policy_references_existing_modules_and_test_functions():
    for filename in SLOW_MODULES | SLOW_TESTS.keys():
        path = ROOT / "tests" / filename
        assert path.is_file(), filename
        functions = {
            node.name
            for node in ast.parse(path.read_text()).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert SLOW_TESTS.get(filename, frozenset()) <= functions, filename


def test_publish_gate_keeps_core_checks_and_one_paired_export():
    for filename, name in (
        ("test_openstudio_cli.py", "test_cli_version_prints_version"),
        (
            "test_openstudio_cli.py",
            "test_cli_doctor_reports_plugin_runtime_contract_mismatch",
        ),
        (
            "test_openstudio_cli.py",
            "test_cli_export_paired_marketplace_includes_provenance",
        ),
        ("test_failure_reporting.py", "test_unstructured_log_redaction"),
        ("test_harness_asset_manifest.py", "test_manifest_sources_are_tracked_in_git"),
    ):
        assert not is_slow_test(filename, name)
    assert not is_slow_test("test_new_unit.py", "test_new_behavior")


def test_expensive_boundaries_are_slow():
    for filename, name in (
        ("test_vav_sizing.py", "test_native_sizing"),
        ("test_mcp_openstudio_smoke.py", "test_server"),
        (
            "test_package_contents.py",
            "test_release_archives_exclude_local_openstudio_fixtures",
        ),
        (
            "test_geometry_viewer.py",
            "test_geometry_viewer_runs_in_a_browser_and_supports_selection",
        ),
        (
            "test_failure_reporting.py",
            "test_native_public_remover_failure_saves_receipt_and_preserves_source",
        ),
    ):
        assert is_slow_test(filename, name)


def test_publish_uses_fast_selection_and_ci_retains_the_full_suite():
    if not (ROOT / ".github/workflows/publish-pypi.yml").is_file():
        pytest.skip("Workflow sources are absent from this source package")
    # BaseLoader preserves GitHub's "on" key as a string under YAML 1.1.
    publish = yaml.load(
        (ROOT / ".github/workflows/publish-pypi.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    ci = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    publish_steps = publish["jobs"]["build"]["steps"]
    runs = [step["run"] for step in publish_steps if "run" in step]
    tests = [command for command in runs if "-m pytest" in command]
    assert len(tests) == 1 and '-m "not slow"' in tests[0]
    assert "playwright install" not in "\n".join(runs)
    assert any("python -m build" in command for command in runs)
    assert any("python -m twine check" in command for command in runs)
    assert publish["jobs"]["publish"]["needs"] == "build"
    ci_runs = [step["run"] for step in ci["jobs"]["test"]["steps"] if "run" in step]
    full = [command for command in ci_runs if "-m pytest" in command]
    assert len(full) == 1 and "-m pytest -q tests" in full[0]
    assert ' -m "' not in full[0]
    assert "--durations=" in full[0]
    assert "pull_request" in ci["on"] and "workflow_dispatch" in ci["on"]
