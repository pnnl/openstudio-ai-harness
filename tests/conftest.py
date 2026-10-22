"""Keep expensive integration checks out of the publishing test gate.

Plain ``pytest tests`` still runs every test. The slow marker changes selection
only when a caller explicitly uses ``-m slow`` or ``-m 'not slow'``.
"""

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent

# These modules repeatedly construct/translate models, simulate, export complete
# plugins, invoke native processes, or build distribution archives.
SLOW_MODULES = frozenset(
    {
        "test_cav_system.py",
        "test_boiler_performance.py",
        "test_terminal_edit.py",
        "test_terminal_replacement.py",
        "test_coil_conversion.py",
        "test_coil_relocation.py",
        "test_economizer.py",
        "test_heat_recovery.py",
        "test_hvac_visualizer.py",
        "test_mcp_openstudio_smoke.py",
        "test_model_preparation.py",
        "test_openstudio_claude_code_adapter.py",
        "test_openstudio_codex_adapter.py",
        "test_outdoor_air_attach.py",
        "test_package_contents.py",
        "test_plant_and_removal_bundles.py",
        "test_pump_performance.py",
        "test_pump_replacement.py",
        "test_sdk_followup_regressions.py",
        "test_sdk_import_closure.py",
        "test_sdk_review_regressions.py",
        "test_sdk_round3_regressions.py",
        "test_sdk_round4_regressions.py",
        "test_shared_sdk_packaging.py",
        "test_supply_fan_performance.py",
        "test_supply_fan_replacement.py",
        "test_vav_apply.py",
        "test_vav_preflight.py",
        "test_vav_sizing.py",
        "test_ventilation.py",
        "test_water_coil_migration.py",
        "test_water_coil_operations.py",
    }
)

# Mixed modules keep their small unit tests in the release gate. One paired
# marketplace export remains fast as the release's plugin/contract smoke check.
SLOW_TESTS = {
    "test_openstudio_cli.py": frozenset(
        {
            "test_cli_export_claude_marketplace",
            "test_cli_validate_export",
            "test_cli_validate_export_rejects_missing_marketplace_setup",
            "test_cli_validate_export_rejects_missing_compatibility_metadata",
            "test_cli_validate_export_allows_historical_metadata_unless_strict",
        }
    ),
    "test_failure_reporting.py": frozenset(
        {
            "test_reporter_survives_missing_shared_sdk_and_relocation",
            "test_native_public_remover_failure_saves_receipt_and_preserves_source",
        }
    ),
    "test_geometry_viewer.py": frozenset(
        {"test_geometry_viewer_runs_in_a_browser_and_supports_selection"}
    ),
    "test_openstudio_sdk_docs.py": frozenset(
        {
            "test_from_env_falls_back_to_bundled_docs_for_invalid_override",
            "test_bundled_docs_contain_airloophvac",
            "test_bundled_docs_list_methods_for_airloophvac",
            "test_bundled_docs_get_method_returns_signature",
        }
    ),
    "test_skill_sdk_doctor.py": frozenset(
        {"test_exported_sdk_doctor_blocks_missing_release_without_runtime"}
    ),
}


def is_slow_test(filename: str, test_name: str) -> bool:
    return filename in SLOW_MODULES or test_name in SLOW_TESTS.get(filename, ())


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if item.path.parent.resolve() == TESTS_DIR and is_slow_test(
            item.path.name, getattr(item, "originalname", None) or item.name
        ):
            item.add_marker(pytest.mark.slow)
