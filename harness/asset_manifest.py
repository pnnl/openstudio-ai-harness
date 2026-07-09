from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MANIFEST_PATH = Path(__file__).with_name("asset_manifest.yaml")

ALLOWED_KINDS = {
    "agent_prompt",
    "orchestration_prompt",
    "workflow_state_reference",
    "learning_reference",
    "promotion_reference",
    "knowledge_reference",
    "workflow_state_schema",
    "learning_schema",
}
ALLOWED_LABELS = {
    "prompt",
    "agent",
    "orchestration",
    "harness",
    "blackboard",
    "workflow_state",
    "learning",
    "governance",
    "promotion",
    "knowledge",
    "sdk",
    "recipes",
    "wiki",
    "schema",
    "measure",
    "recipe",
    "session_lesson",
    "runtime",
}
ALLOWED_HOSTS = {"claude", "codex"}
ALLOWED_ROLES = {"agent_template", "skill_reference"}


@dataclass(frozen=True)
class AssetExport:
    """A concrete source-to-target copy derived from the asset manifest."""

    source: Path
    target: Path
    kind: str
    labels: tuple[str, ...]
    role: str


def reference_exports_for_host(
    workspace_root: Path,
    plugin_dir: Path,
    host: str,
) -> list[AssetExport]:
    """Return manifest-declared copied assets for a host plugin export."""
    workspace_root = workspace_root.resolve()
    plugin_dir = plugin_dir.resolve()
    manifest = _load_manifest()
    exports: list[AssetExport] = []

    for asset in manifest.get("assets", []):
        if not isinstance(asset, dict):
            continue
        host_config = _host_config(asset, host)
        if not host_config or host_config.get("copy", True) is False:
            continue
        source_pattern = asset.get("path")
        if not isinstance(source_pattern, str) or not source_pattern:
            continue
        sources = _expand_sources(workspace_root, source_pattern)
        kind = str(asset.get("kind", "reference"))
        labels = tuple(str(label) for label in asset.get("labels", []))
        role = str(host_config.get("role", "skill_reference"))
        targets = host_config.get("targets")
        target_dir = host_config.get("target_dir")

        if isinstance(targets, list):
            for source in sources:
                for target in targets:
                    if isinstance(target, str) and target:
                        exports.append(
                            AssetExport(
                                source=source,
                                target=plugin_dir / target,
                                kind=kind,
                                labels=labels,
                                role=role,
                            )
                        )
            continue

        if isinstance(target_dir, str) and target_dir:
            for source in sources:
                exports.append(
                    AssetExport(
                        source=source,
                        target=plugin_dir / target_dir / source.name,
                        kind=kind,
                        labels=labels,
                        role=role,
                    )
                )

    return sorted(exports, key=lambda export: str(export.target))


def _load_manifest() -> dict[str, Any]:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid asset manifest: {MANIFEST_PATH}")
    _validate_manifest(data)
    return data


def _validate_manifest(data: dict[str, Any]) -> None:
    if data.get("version") != 1:
        raise ValueError("asset_manifest.yaml must declare version: 1")
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise ValueError("asset_manifest.yaml must contain an assets list")
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise ValueError(f"Asset manifest entry {index} must be an object")
        _validate_asset(asset, index)


def _validate_asset(asset: dict[str, Any], index: int) -> None:
    path = asset.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError(f"Asset manifest entry {index} must define path")
    kind = asset.get("kind")
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"Asset manifest entry {path} has unsupported kind: {kind}")
    labels = asset.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError(f"Asset manifest entry {path} must define labels")
    unsupported_labels = sorted(set(labels) - ALLOWED_LABELS)
    if unsupported_labels:
        raise ValueError(
            f"Asset manifest entry {path} has unsupported labels: {unsupported_labels}"
        )
    hosts = asset.get("hosts")
    if not isinstance(hosts, dict) or not hosts:
        raise ValueError(f"Asset manifest entry {path} must define hosts")
    unsupported_hosts = sorted(set(hosts) - ALLOWED_HOSTS)
    if unsupported_hosts:
        raise ValueError(
            f"Asset manifest entry {path} has unsupported hosts: {unsupported_hosts}"
        )
    for host, config in hosts.items():
        if not isinstance(config, dict):
            raise ValueError(
                f"Asset manifest entry {path} host {host} must be an object"
            )
        _validate_host_config(path, host, config)


def _validate_host_config(path: str, host: str, config: dict[str, Any]) -> None:
    role = config.get("role")
    if role not in ALLOWED_ROLES:
        raise ValueError(
            f"Asset manifest entry {path} host {host} has unsupported role: {role}"
        )
    has_generated_target = isinstance(config.get("generated_target"), str)
    has_targets = isinstance(config.get("targets"), list)
    has_target_dir = isinstance(config.get("target_dir"), str)
    if sum([has_generated_target, has_targets, has_target_dir]) != 1:
        raise ValueError(
            f"Asset manifest entry {path} host {host} must define exactly one of "
            "generated_target, targets, or target_dir"
        )


def _host_config(asset: dict[str, Any], host: str) -> dict[str, Any] | None:
    hosts = asset.get("hosts")
    if not isinstance(hosts, dict):
        return None
    config = hosts.get(host)
    return config if isinstance(config, dict) else None


def _expand_sources(workspace_root: Path, source_pattern: str) -> list[Path]:
    if "*" in source_pattern:
        return sorted(workspace_root.glob(source_pattern))
    source = workspace_root / source_pattern
    return [source] if source.exists() else []
