from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

MANIFEST_PATH = Path(__file__).with_name("asset_manifest.yaml")
ALLOWED_HOSTS = {"claude", "codex"}


@dataclass(frozen=True)
class SkillExport:
    """A canonical product skill rendered into a host plugin."""

    source: Path
    target: Path
    skill: str


@dataclass(frozen=True)
class ReferenceExport:
    """A source file copied into an owning skill's references directory."""

    source: Path
    target: Path
    skill: str


def skill_exports_for_host(
    workspace_root: Path,
    plugin_dir: Path,
    host: str,
) -> list[SkillExport]:
    """Return manifest-registered product skills for a host plugin."""
    _validate_host(host)
    workspace_root = workspace_root.resolve()
    plugin_dir = plugin_dir.resolve()
    exports: list[SkillExport] = []

    for skill in _load_manifest()["skills"]:
        if host not in skill["hosts"]:
            continue
        source = workspace_root / skill["source"]
        if not source.is_file():
            raise ValueError(f"Skill source does not exist: {source}")
        exports.append(
            SkillExport(
                source=source,
                target=plugin_dir / "skills" / skill["id"] / "SKILL.md",
                skill=skill["id"],
            )
        )

    return sorted(exports, key=lambda export: export.skill)


def skill_sources_for_host(workspace_root: Path, host: str) -> list[Path]:
    """Return canonical product skill source files registered for a host."""
    _validate_host(host)
    workspace_root = workspace_root.resolve()
    sources: list[Path] = []
    for skill in _load_manifest()["skills"]:
        if host in skill["hosts"]:
            sources.append(workspace_root / skill["source"])
    return sources


def skill_ids_for_host(workspace_root: Path, host: str) -> list[str]:
    """Return manifest skill identifiers registered for a host."""
    _validate_host(host)
    return sorted(
        skill["id"] for skill in _load_manifest()["skills"] if host in skill["hosts"]
    )


def reference_exports_for_host(
    workspace_root: Path,
    plugin_dir: Path,
    host: str,
) -> list[ReferenceExport]:
    """Return skill-owned reference copies declared for a host."""
    _validate_host(host)
    workspace_root = workspace_root.resolve()
    plugin_dir = plugin_dir.resolve()
    exports: list[ReferenceExport] = []

    for reference in _load_manifest()["references"]:
        sources = _expand_sources(workspace_root, reference["source"])
        for owner in reference["owners"]:
            if host not in owner["hosts"]:
                continue
            reference_dir = plugin_dir / "skills" / owner["skill"] / "references"
            subdirectory = owner.get("subdirectory")
            if subdirectory:
                reference_dir /= subdirectory
            for source in sources:
                exports.append(
                    ReferenceExport(
                        source=source,
                        target=reference_dir / source.name,
                        skill=owner["skill"],
                    )
                )

    return sorted(exports, key=lambda export: str(export.target))


def agent_source_for_host(workspace_root: Path, host: str, name: str) -> Path:
    """Return the manifest-declared source prompt for a generated host agent."""
    _validate_host(host)
    workspace_root = workspace_root.resolve()

    for agent in _load_manifest()["agents"]:
        if agent["id"] != name or host not in agent["hosts"]:
            continue
        source = workspace_root / agent["source"]
        if not source.is_file():
            raise ValueError(f"Agent source does not exist: {source}")
        return source

    raise ValueError(
        f"No {host} agent named {name!r} is declared in the asset manifest"
    )


def _load_manifest() -> dict[str, Any]:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid asset manifest: {MANIFEST_PATH}")
    _validate_manifest(data)
    return data


def _validate_manifest(data: dict[str, Any]) -> None:
    if data.get("version") != 3:
        raise ValueError("asset_manifest.yaml must declare version: 3")
    skills = data.get("skills")
    agents = data.get("agents")
    references = data.get("references")
    if (
        not isinstance(skills, list)
        or not isinstance(agents, list)
        or not isinstance(references, list)
    ):
        raise ValueError(
            "asset_manifest.yaml must contain skills, agents, and references lists"
        )

    skill_hosts: dict[str, set[str]] = {}
    for index, skill in enumerate(skills):
        _validate_skill(skill, index, skill_hosts)
    for index, agent in enumerate(agents):
        _validate_agent(agent, index)
    for index, reference in enumerate(references):
        _validate_reference(reference, index, skill_hosts)


def _validate_skill(
    skill: Any,
    index: int,
    skill_hosts: dict[str, set[str]],
) -> None:
    if not isinstance(skill, dict):
        raise ValueError(f"Skill manifest entry {index} must be an object")
    _validate_fields(skill, {"id", "source", "hosts"}, "skill", index)
    skill_id = _required_safe_name(skill, "id", "skill", index)
    if skill_id in skill_hosts:
        raise ValueError(f"Skill manifest contains duplicate id: {skill_id}")
    source = skill.get("source")
    if not isinstance(source, str) or not source or "*" in source:
        raise ValueError(f"Skill manifest entry {skill_id} must define one source file")
    skill_hosts[skill_id] = set(_validate_hosts(skill.get("hosts"), "skill", skill_id))


def _validate_agent(agent: Any, index: int) -> None:
    if not isinstance(agent, dict):
        raise ValueError(f"Agent manifest entry {index} must be an object")
    _validate_fields(agent, {"id", "source", "hosts"}, "agent", index)
    agent_id = _required_safe_name(agent, "id", "agent", index)
    source = agent.get("source")
    if not isinstance(source, str) or not source or "*" in source:
        raise ValueError(f"Agent manifest entry {agent_id} must define one source file")
    hosts = _validate_hosts(agent.get("hosts"), "agent", agent_id)
    if hosts != ["claude"]:
        raise ValueError(
            f"Agent manifest entry {agent_id} is only supported for Claude"
        )


def _validate_reference(
    reference: Any,
    index: int,
    skill_hosts: dict[str, set[str]],
) -> None:
    if not isinstance(reference, dict):
        raise ValueError(f"Reference manifest entry {index} must be an object")
    _validate_fields(reference, {"source", "owners"}, "reference", index)
    source = reference.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError(f"Reference manifest entry {index} must define source")
    owners = reference.get("owners")
    if not isinstance(owners, list) or not owners:
        raise ValueError(f"Reference manifest entry {source} must define owners")
    for owner in owners:
        _validate_owner(source, owner, skill_hosts)


def _validate_owner(
    source: str,
    owner: Any,
    skill_hosts: dict[str, set[str]],
) -> None:
    if not isinstance(owner, dict):
        raise ValueError(f"Reference manifest entry {source} owner must be an object")
    allowed_fields = {"hosts", "skill", "subdirectory"}
    unexpected_fields = sorted(set(owner) - allowed_fields)
    if unexpected_fields:
        raise ValueError(
            f"Reference manifest entry {source} owner has unsupported fields: "
            f"{unexpected_fields}"
        )
    skill = owner.get("skill")
    if not isinstance(skill, str) or skill not in skill_hosts:
        raise ValueError(
            f"Reference manifest entry {source} names unknown skill: {skill}"
        )
    hosts = set(_validate_hosts(owner.get("hosts"), "reference owner", source))
    if not hosts.issubset(skill_hosts[skill]):
        raise ValueError(
            f"Reference manifest entry {source} assigns hosts not exported by {skill}"
        )
    subdirectory = owner.get("subdirectory")
    if subdirectory is not None and (
        not isinstance(subdirectory, str) or not _is_safe_relative_path(subdirectory)
    ):
        raise ValueError(
            f"Reference manifest entry {source} subdirectory must be a safe relative path"
        )


def _validate_fields(
    entry: dict[str, Any], allowed_fields: set[str], entry_type: str, index: int
) -> None:
    unexpected_fields = sorted(set(entry) - allowed_fields)
    if unexpected_fields:
        raise ValueError(
            f"{entry_type.title()} manifest entry {index} has unsupported fields: "
            f"{unexpected_fields}"
        )


def _required_safe_name(
    entry: dict[str, Any], field: str, entry_type: str, index: int
) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not _is_safe_name(value):
        raise ValueError(
            f"{entry_type.title()} manifest entry {index} must define a safe {field}"
        )
    return value


def _validate_hosts(hosts: Any, entry_type: str, identity: str) -> list[str]:
    if (
        not isinstance(hosts, list)
        or not hosts
        or not all(isinstance(host, str) for host in hosts)
    ):
        raise ValueError(
            f"{entry_type.title()} manifest entry {identity} must define a non-empty hosts list"
        )
    unsupported_hosts = sorted(set(hosts) - ALLOWED_HOSTS)
    if unsupported_hosts or len(set(hosts)) != len(hosts):
        raise ValueError(
            f"{entry_type.title()} manifest entry {identity} has invalid hosts: {hosts}"
        )
    return hosts


def _validate_host(host: str) -> None:
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Unsupported host: {host}")


def _is_safe_name(value: str) -> bool:
    return value == Path(value).name and value not in {"", ".", ".."}


def _is_safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _expand_sources(workspace_root: Path, source_pattern: str) -> list[Path]:
    if "*" in source_pattern:
        return sorted(
            path for path in workspace_root.glob(source_pattern) if path.is_file()
        )
    source = workspace_root / source_pattern
    return [source] if source.is_file() else []
