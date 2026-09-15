from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from adapters.base import OpenStudioAiHostAdapter
from adapters.contracts import HostAdapterConfig, HostLaunchPlan
from harness.registry import discover_harness_assets
from openstudio_ai_mcp.compatibility import package_version

DEFAULT_PLUGIN_NAME = "openstudio-ai"


@dataclass(frozen=True)
class OpenCodePluginExportResult:
    """Result of exporting a self-contained OpenCode plugin module."""

    dry_run: bool
    plugin_dir: Path
    files: list[Path]


class OpenCodeAdapter(OpenStudioAiHostAdapter):
    """Export the OpenCode session-policy adapter.

    OpenCode plugins are JavaScript modules, unlike Claude and Codex plugin
    folders. The module deliberately supplies policy only: ``openstudio_ai``
    and optional ``bem-calibration`` remain separately configured MCP
    connections, so the plugin never attempts to duplicate or launch either
    service.
    """

    def build_launch_plan(self) -> HostLaunchPlan:
        assets = discover_harness_assets(self.config.workspace_root)
        return HostLaunchPlan(
            host_name="opencode",
            system_prompt_files=assets.prompt_contracts,
            skill_paths=[],
            mcp_entrypoint=assets.mcp_entrypoint,
            blackboard_schema=assets.blackboard_schema,
            learning_event_log=assets.learning_event_log,
            notes=[
                "Inject the OpenStudio workflow policy through OpenCode's system hook.",
                "Use separately configured openstudio_ai and bem-calibration MCP servers.",
            ],
        )

    def export_plugin(
        self,
        output_dir: Path,
        *,
        plugin_name: str = DEFAULT_PLUGIN_NAME,
        dry_run: bool = True,
        force: bool = False,
    ) -> OpenCodePluginExportResult:
        """Export a local OpenCode module that can be referenced with ``file://``."""
        if not plugin_name or "/" in plugin_name or "\\" in plugin_name:
            raise ValueError("OpenCode plugin_name must be a non-empty directory name")

        plugin_dir = output_dir.resolve() / plugin_name
        files = [
            plugin_dir / "package.json",
            plugin_dir / "index.mjs",
            plugin_dir / "README.md",
        ]
        if dry_run:
            return OpenCodePluginExportResult(True, plugin_dir, files)

        if plugin_dir.exists():
            if not force:
                raise FileExistsError(
                    f"{plugin_dir} already exists. Use --force to replace it."
                )
            shutil.rmtree(plugin_dir)

        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "package.json").write_text(
            _render_package_json(plugin_name), encoding="utf-8"
        )
        (plugin_dir / "index.mjs").write_text(
            _render_plugin_module(plugin_name), encoding="utf-8"
        )
        (plugin_dir / "README.md").write_text(
            _render_readme(plugin_name), encoding="utf-8"
        )
        return OpenCodePluginExportResult(False, plugin_dir, files)


def _render_package_json(plugin_name: str) -> str:
    return json.dumps(
        {
            "name": plugin_name,
            "version": package_version(),
            "private": True,
            "type": "module",
            "description": "OpenStudio AI LBNL development policy adapter for OpenCode",
        },
        indent=2,
        ensure_ascii=True,
    ) + "\n"


def _render_plugin_module(plugin_name: str) -> str:
    guidance = _system_guidance(plugin_name)
    return (
        "// Generated from the OpenStudio AI Harness. Do not edit this export;\n"
        "// change adapters/opencode_adapter.py and re-export instead.\n\n"
        f"const SYSTEM_GUIDANCE = {json.dumps(guidance, ensure_ascii=True)};\n\n"
        "export const OpenStudioAiLbnlDev = async () => ({\n"
        '  "experimental.chat.system.transform": async (_input, output) => {\n'
        "    if (!output.system.includes(SYSTEM_GUIDANCE)) {\n"
        "      output.system.push(SYSTEM_GUIDANCE);\n"
        "    }\n"
        "  },\n"
        "});\n\n"
        "export default OpenStudioAiLbnlDev;\n"
    )


def _system_guidance(plugin_name: str) -> str:
    """Keep OpenCode's injected policy concise and host-neutral.

    Detailed calibration methodology remains discoverable at runtime from the
    LBNL service rather than being copied into this host plugin.
    """
    return f"""# OpenStudio AI LBNL Development Policy

This OpenCode plugin ({plugin_name}) supplies routing and safety policy only.
Use the separately configured `openstudio_ai` MCP for OpenStudio workflow
state, provenance, artifacts, modeling, simulation, results, and SDK lookup.
Use the separately configured optional `bem-calibration` MCP only for
measured-bill calibration. Do not treat either service as installed merely
because this policy is present; inspect the tools available in the current
session first.

## OpenStudio workflow

- For an OpenStudio request, establish model identity, format, paths, the
  intended execution provider, and relevant OpenStudio/EnergyPlus versions
  before mutation or simulation. Ask one focused question if a material input
  is missing or an action is ambiguous.
- Keep workflow state and artifact provenance in `openstudio_ai`'s blackboard.
  Record provider identity, model lineage, host/container path mapping, run
  identifiers, hashes when available, and warnings. Provider container paths
  are not host-shell paths.
- When `openstudio-mcp` is available and compatible, preflight it and use one
  selected provider exclusively for a modeling phase. Do not let it and
  `openstudio_ai` mutate the same unstaged model. `openstudio_ai` retains
  blackboard and artifact ownership; use its own modeling route only after an
  explicit recorded provider transition or when the delegated provider is
  unsuitable.
- Use `model_*` tools for controlled model lifecycle and validation, `sim_*`
  for simulation execution and artifacts, `results_*` for SQL-backed results,
  and `sdk_docs_*` before non-obvious OpenStudio SDK calls. Do not replace
  simulation, polling, artifact retrieval, or SQL queries with ad-hoc host
  scripts.
- Before a non-trivial workflow action, search applicable personal lessons
  through the MCP. They are local guidance only and must not be promoted to
  trusted assets automatically.

## Measured-bill calibration

- Start calibration only for a measured-bill request and only when
  `bem-calibration` is actually connected. Its blackboard identity is
  `lbnl_bem_calibration`; it is a domain service, never an execution provider.
- Discover the authoritative `pattern-based-calibration` methodology from the
  live Calibration-MCP session using its advertised `skills/list`, `skills/get`,
  and `skill://` resources. Do not substitute a copied local skill when that
  discovery is unavailable.
- Calibration-MCP owns arithmetic, state, accepted candidates, ledger, and
  final reports. It never edits a model or runs a simulation. The selected
  execution provider owns model changes and EnergyPlus evidence. Keep its run
  identifiers distinct from Calibration-MCP ledger identifiers.
- Before the baseline, validate bill units, weather/calendar, model/provider
  versions, host-visible `runs_dir`, canonical monthly electricity and gas SQL
  evidence, meter/reach gates, and staged-model lineage. Use a dedicated empty
  run directory for a calibration project.
- Preserve an auditable stepwise loop: record the domain decision, checkpoint
  before and after critical mutations and simulations, wait for canonical
  `run_record.json` and `eplusout.sql`, then record the ledger result. A report
  is converged only when Calibration-MCP's final report and evidence say so.
  Report unavailable or non-converged outcomes honestly.
"""


def _render_readme(plugin_name: str) -> str:
    return f"""# {plugin_name}

This is a local OpenCode plugin exported from the OpenStudio AI Harness. It
injects the LBNL OpenStudio/calibration routing policy into OpenCode chats. It
does not start or package MCP services.

## Required connections

Configure `openstudio_ai` for the OpenStudio AI MCP and, for measured-bill
calibration, `bem-calibration` for LBNL Calibration-MCP. The plugin checks no
connection itself; OpenCode exposes whichever MCP tools are configured for the
session.

## Local installation

Add this module's absolute `file://` URL to the global `plugin` array in
`~/.config/opencode/opencode.jsonc`, for example:

```jsonc
{{
  "plugin": [
    "file:///absolute/path/to/{plugin_name}/index.mjs"
  ]
}}
```

Restart OpenCode or start a new session after changing the configuration. This
module is intentionally local-development only; change the harness source and
re-export rather than editing `index.mjs`.
"""
