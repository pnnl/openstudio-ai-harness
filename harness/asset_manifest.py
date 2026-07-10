from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

MANIFEST_PATH = Path(__file__).with_name("asset_manifest.yaml")
ALLOWED_HOSTS = {"claude", "codex"}


@dataclass(frozen=True)
class AssetExport:
    """A source file copied into a host skill's references directory."""

    source: Path
    target: Path
    skill: str


def reference_exports_for_host(
    workspace_root: Path,
    plugin_dir: Path,
    host: str,
) -> list[AssetExport]:
    """Return skill-owned reference copies declared for a host."""
    _validate_host(host)
    workspace_root = workspace_root.resolve()
    plugin_dir = plugin_dir.resolve()
    exports: list[AssetExport] = []

    for asset in _load_manifest()["assets"]:
        source_pattern = asset["path"]
        sources = _expand_sources(workspace_root, source_pattern)
        for reference in asset.get("references", []):
            if host not in reference["hosts"]:
                continue
            reference_dir = plugin_dir / "skills" / reference["skill"] / "references"
            subdirectory = reference.get("subdirectory")
            if subdirectory:
                reference_dir /= subdirectory
            for source in sources:
                exports.append(
                    AssetExport(
                        source=source,
                        target=reference_dir / source.name,
                        skill=reference["skill"],
                    )
                )

    return sorted(exports, key=lambda export: str(export.target))


def agent_source_for_host(workspace_root: Path, host: str, name: str) -> Path:
    """Return the manifest-declared source prompt for a generated host agent."""
    _validate_host(host)
    workspace_root = workspace_root.resolve()

    for asset in _load_manifest()["assets"]:
        agent = asset.get("agent")
        if not isinstance(agent, dict):
            continue
        if agent["name"] != name or host not in agent["hosts"]:
            continue
        source = workspace_root / asset["path"]
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
    if data.get("version") != 2:
        raise ValueError("asset_manifest.yaml must declare version: 2")
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise ValueError("asset_manifest.yaml must contain an assets list")
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise ValueError(f"Asset manifest entry {index} must be an object")
        _validate_asset(asset, index)


def _validate_asset(asset: dict[str, Any], index: int) -> None:
    allowed_fields = {"path", "agent", "references"}
    unexpected_fields = sorted(set(asset) - allowed_fields)
    if unexpected_fields:
        raise ValueError(
            f"Asset manifest entry {index} has unsupported fields: {unexpected_fields}"
        )
    path = asset.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError(f"Asset manifest entry {index} must define path")

    references = asset.get("references", [])
    agent = asset.get("agent")
    if not references and agent is None:
        raise ValueError(f"Asset manifest entry {path} must define agent or references")
    if not isinstance(references, list):
        raise ValueError(f"Asset manifest entry {path} references must be a list")
    for reference in references:
        _validate_reference(path, reference)
    if agent is not None:
        _validate_agent(path, agent)


def _validate_reference(path: str, reference: Any) -> None:
    if not isinstance(reference, dict):
        raise ValueError(f"Asset manifest entry {path} reference must be an object")
    allowed_fields = {"hosts", "skill", "subdirectory"}
    unexpected_fields = sorted(set(reference) - allowed_fields)
    if unexpected_fields:
        raise ValueError(
            f"Asset manifest entry {path} reference has unsupported fields: "
            f"{unexpected_fields}"
        )
    _validate_hosts(path, reference.get("hosts"), "reference")
    skill = reference.get("skill")
    if not isinstance(skill, str) or not _is_safe_name(skill):
        raise ValueError(
            f"Asset manifest entry {path} reference must define a safe skill"
        )
    subdirectory = reference.get("subdirectory")
    if subdirectory is not None and (
        not isinstance(subdirectory, str) or not _is_safe_relative_path(subdirectory)
    ):
        raise ValueError(
            f"Asset manifest entry {path} reference subdirectory must be a safe relative path"
        )


def _validate_agent(path: str, agent: Any) -> None:
    if not isinstance(agent, dict):
        raise ValueError(f"Asset manifest entry {path} agent must be an object")
    allowed_fields = {"hosts", "name"}
    unexpected_fields = sorted(set(agent) - allowed_fields)
    if unexpected_fields:
        raise ValueError(
            f"Asset manifest entry {path} agent has unsupported fields: {unexpected_fields}"
        )
    hosts = _validate_hosts(path, agent.get("hosts"), "agent")
    if hosts != ["claude"]:
        raise ValueError(
            f"Asset manifest entry {path} agent is only supported for Claude"
        )
    name = agent.get("name")
    if not isinstance(name, str) or not _is_safe_name(name):
        raise ValueError(f"Asset manifest entry {path} agent must define a safe name")


def _validate_hosts(path: str, hosts: Any, delivery: str) -> list[str]:
    if (
        not isinstance(hosts, list)
        or not hosts
        or not all(isinstance(host, str) for host in hosts)
    ):
        raise ValueError(
            f"Asset manifest entry {path} {delivery} must define a non-empty hosts list"
        )
    unsupported_hosts = sorted(set(hosts) - ALLOWED_HOSTS)
    if unsupported_hosts or len(set(hosts)) != len(hosts):
        raise ValueError(
            f"Asset manifest entry {path} {delivery} has invalid hosts: {hosts}"
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
