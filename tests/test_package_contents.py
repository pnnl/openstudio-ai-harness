from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def test_release_archives_exclude_local_openstudio_fixtures(tmp_path: Path) -> None:
    """Keep local fixtures out of both release artifacts."""
    result = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()

    wheel_blocked_prefixes = (
        "resource/",
        "tests/",
        "evals/",
        "measures/candidates/",
    )
    wheel_blocked = [
        name for name in wheel_names if name.startswith(wheel_blocked_prefixes)
    ]
    assert not wheel_blocked
    assert "scripts/evaluate_skill_vav.py" not in wheel_names
    assert "skills/sdk_scripts/common/companions.py" in wheel_names
    assert "skills/sdk_scripts/common/files.py" in wheel_names
    assert "openstudio_ai_mcp/model_resources.py" in wheel_names
    assert "openstudio_ai_mcp/server.py" in wheel_names
    assert "openstudio_ai_mcp/compatibility.py" in wheel_names
    assert "openstudio_ai_mcp/sdk_docs/docs/api/classes-3.10.0.yaml.gz" in wheel_names
    assert "openstudio_ai_mcp/sdk_docs/docs/api/methods-3.10.0.yaml.gz" in wheel_names
    assert "skills/openstudio_vav_reheat_system_creator.md" in wheel_names
    assert "harness/plugin_sdk.py" in wheel_names
    assert "skills/report_openstudio_failure.md" in wheel_names
    assert "skills/sdk_scripts/common/failure_reporting.py" in wheel_names
    assert "skills/failure_reporting/event.schema.json" in wheel_names
    assert "skills/openstudio_hvac_visualizer.md" in wheel_names
    assert "skills/sdk_scripts/visualize_hvac.py" in wheel_names
    assert "skills/sdk_scripts/common/hvac_graph.py" in wheel_names
    assert "skills/sdk_scripts/common/hvac_diagram.py" in wheel_names
    assert "skills/sdk_scripts/schemas/hvac_graph.schema.json" in wheel_names
    assert "prompts/openstudio_agent.md" in wheel_names

    sdist = next(tmp_path.glob("*.tar.gz"))
    with tarfile.open(sdist) as archive:
        sdist_names = [member.name.partition("/")[2] for member in archive.getmembers()]

    terminal_sources = {
        "skills/openstudio_tower_performance_editor.md",
        "skills/sdk_scripts/edit_tower_performance.py",
        "skills/sdk_scripts/common/tower_edit.py",
        "skills/sdk_scripts/references/tower_performance.md",
        "skills/sdk_scripts/references/tower_performance.schema.json",
        "skills/openstudio_chiller_performance_editor.md",
        "skills/sdk_scripts/edit_chiller_performance.py",
        "skills/sdk_scripts/common/chiller_edit.py",
        "skills/sdk_scripts/references/chiller_performance.md",
        "skills/sdk_scripts/references/chiller_performance.schema.json",
        "skills/openstudio_boiler_performance_editor.md",
        "skills/sdk_scripts/edit_boiler_performance.py",
        "skills/sdk_scripts/common/boiler_edit.py",
        "skills/sdk_scripts/references/boiler_performance.md",
        "skills/sdk_scripts/references/boiler_performance.schema.json",
        "skills/openstudio_terminal_replacer.md",
        "skills/sdk_scripts/replace_terminal.py",
        "skills/sdk_scripts/common/terminal_replacement.py",
        "skills/sdk_scripts/references/terminal_replacement.md",
        "skills/sdk_scripts/references/terminal_replacement.schema.json",
        "skills/openstudio_terminal_editor.md",
        "skills/sdk_scripts/edit_terminal.py",
        "skills/sdk_scripts/common/terminal_edit.py",
        "skills/sdk_scripts/references/terminal_edit.md",
        "skills/sdk_scripts/references/terminal_edit.schema.json",
    }
    assert terminal_sources <= set(wheel_names)
    assert terminal_sources <= set(sdist_names)

    sdist_blocked_prefixes = (
        "resource/",
        "tests/fixtures/",
        "measures/candidates/",
    )
    sdist_blocked = [
        name for name in sdist_names if name.startswith(sdist_blocked_prefixes)
    ]
    assert not sdist_blocked
