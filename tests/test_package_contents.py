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
    assert "openstudio_mcp/server.py" in wheel_names
    assert "openstudio_mcp/compatibility.py" in wheel_names
    assert "openstudio_mcp/sdk_docs/docs/api/classes-3.10.0.yaml.gz" in wheel_names
    assert "openstudio_mcp/sdk_docs/docs/api/methods-3.10.0.yaml.gz" in wheel_names
    assert "skills/openstudio_vav_reheat_system_creator.md" in wheel_names
    assert "prompts/openstudio_agent.md" in wheel_names

    sdist = next(tmp_path.glob("*.tar.gz"))
    with tarfile.open(sdist) as archive:
        sdist_names = [member.name.partition("/")[2] for member in archive.getmembers()]

    sdist_blocked_prefixes = (
        "resource/",
        "tests/fixtures/",
        "measures/candidates/",
    )
    sdist_blocked = [
        name for name in sdist_names if name.startswith(sdist_blocked_prefixes)
    ]
    assert not sdist_blocked
