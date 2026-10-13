"""Relocate the deployment unit while retaining a convenient skill path."""

from pathlib import Path
import shutil


def copy_plugin_for_skill(skill: Path, destination: Path) -> Path:
    assert skill.parent.name == "skills"
    shutil.copytree(skill.parent.parent, destination)
    return destination / "skills" / skill.name
