from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from adapters.base import OpenStudioAiHostAdapter
from adapters.contracts import RUNTIME_MODES, HostAdapterConfig, HostLaunchPlan
from adapters.runtime_helpers import (
    doctor_triage_guidance,
    marketplace_mcp_server_config,
    offline_guidance,
    prepare_runtime_guidance,
    runtime_doctor_command,
    runtime_uvx_command,
)
from harness.asset_manifest import (
    reference_exports_for_host,
    skill_exports_for_host,
    skill_ids_for_host,
    skill_sources_for_host,
)
from harness.registry import discover_harness_assets
from openstudio_ai_mcp.compatibility import package_version, plugin_mcp_environment

DEFAULT_PLUGIN_NAME = "openstudio-ai"
MARKETPLACE_NAME = "openstudio-ai-local"
SERVER_NAME = "openstudio_ai"
PLUGIN_ICON_PATH = Path(__file__).with_name("assets") / "openstudio-ai-icon.png"
AGENTS_GENERATED_START = "<!-- BEGIN OPENSTUDIO_AI_HARNESS -->"
AGENTS_GENERATED_END = "<!-- END OPENSTUDIO_AI_HARNESS -->"


@dataclass(frozen=True)
class CodexInstallAction:
    """A single file write planned for Codex project guidance."""

    path: Path
    action: str
    content: str


@dataclass(frozen=True)
class CodexInstallResult:
    """Result for installing managed OpenStudio guidance into a Codex project."""

    dry_run: bool
    target_dir: Path
    actions: list[CodexInstallAction]


@dataclass(frozen=True)
class CodexPluginExportResult:
    """Result for exporting a Codex plugin package and local marketplace."""

    dry_run: bool
    marketplace_path: Path
    plugin_dir: Path
    files: list[Path]


class CodexAdapter(OpenStudioAiHostAdapter):
    """Adapter contract for exporting OpenStudio AI into Codex plugin format."""

    def build_launch_plan(self) -> HostLaunchPlan:
        """Resolve the host-facing assets from the OpenStudio AI harness registry."""
        assets = discover_harness_assets(self.config.workspace_root)
        return HostLaunchPlan(
            host_name="codex",
            system_prompt_files=assets.prompt_contracts,
            skill_paths=skill_sources_for_host(self.config.workspace_root, "codex"),
            mcp_entrypoint=assets.mcp_entrypoint,
            blackboard_schema=assets.blackboard_schema,
            learning_event_log=assets.learning_event_log,
            notes=[
                "Export skills, MCP config, and skill-owned references as a Codex plugin."
            ],
        )

    def build_install_actions(
        self, target_dir: Path, *, force: bool = False
    ) -> list[CodexInstallAction]:
        """Plan a managed OpenStudio policy block for a Codex project's AGENTS.md."""
        target_dir = target_dir.resolve()
        return [
            CodexInstallAction(
                path=target_dir / "AGENTS.md",
                action="write_project_guidance",
                content=_render_codex_agents_instructions(
                    existing_path=target_dir / "AGENTS.md",
                    workspace_root=self.config.workspace_root.resolve(),
                    force=force,
                ),
            )
        ]

    def install(
        self, target_dir: Path, *, dry_run: bool = True, force: bool = False
    ) -> CodexInstallResult:
        """Write or preview the managed OpenStudio policy block for Codex."""
        actions = self.build_install_actions(target_dir, force=force)
        if not dry_run:
            for action in actions:
                action.path.parent.mkdir(parents=True, exist_ok=True)
                action.path.write_text(action.content, encoding="utf-8")
        return CodexInstallResult(
            dry_run=dry_run, target_dir=target_dir.resolve(), actions=actions
        )

    def export_plugin(
        self,
        output_dir: Path,
        *,
        plugin_name: str = DEFAULT_PLUGIN_NAME,
        dry_run: bool = True,
        force: bool = False,
    ) -> CodexPluginExportResult:
        """Export a Codex plugin plus a repo-local marketplace manifest."""
        workspace_root = self.config.workspace_root.resolve()
        export_root = output_dir.resolve()
        plugin_dir = export_root / "plugins" / plugin_name
        marketplace_path = export_root / ".agents" / "plugins" / "marketplace.json"
        plan = self.build_launch_plan()
        runtime_mode = self.config.runtime_mode
        files = _planned_export_files(
            export_root,
            plugin_dir,
            marketplace_path,
            plan,
            workspace_root,
            runtime_mode,
        )

        if dry_run:
            return CodexPluginExportResult(
                dry_run=True,
                marketplace_path=marketplace_path,
                plugin_dir=plugin_dir,
                files=files,
            )

        if plugin_dir.exists():
            if not force:
                raise FileExistsError(
                    f"{plugin_dir} already exists. Use --force to replace it."
                )
            shutil.rmtree(plugin_dir)

        marketplace_path.parent.mkdir(parents=True, exist_ok=True)
        marketplace_path.write_text(
            _render_marketplace_json(plugin_name), encoding="utf-8"
        )
        (export_root / "INSTALL.md").write_text(
            _render_install_doc(
                export_root, marketplace_path, plugin_name, runtime_mode
            ),
            encoding="utf-8",
        )
        _write_plugin_package(plugin_dir, plan, workspace_root, runtime_mode)

        return CodexPluginExportResult(
            dry_run=False,
            marketplace_path=marketplace_path,
            plugin_dir=plugin_dir,
            files=files,
        )


def _render_codex_agents_instructions(
    existing_path: Path, workspace_root: Path, *, force: bool
) -> str:
    """Render or update the managed OpenStudio block in a project's AGENTS.md.

    Codex does not activate an arbitrary plugin agent prompt as the main thread.
    Installing the shared modeler policy into the project gives natural-language
    OpenStudio requests the same orchestration gate that Claude receives through
    its plugin agent, without replacing the project's own instructions.
    """
    generated = _generated_codex_agents_block(workspace_root)
    if not existing_path.exists():
        return generated

    existing = existing_path.read_text(encoding="utf-8")
    if AGENTS_GENERATED_START in existing and AGENTS_GENERATED_END in existing:
        before, rest = existing.split(AGENTS_GENERATED_START, 1)
        _, after = rest.split(AGENTS_GENERATED_END, 1)
        return before.rstrip() + "\n\n" + generated + "\n" + after.lstrip()

    if not force:
        raise FileExistsError(
            f"{existing_path} already exists and is not managed by OpenStudio AI. "
            "Use --force to append the generated OpenStudio AI block."
        )

    return existing.rstrip() + "\n\n" + generated


def _generated_codex_agents_block(workspace_root: Path) -> str:
    """Return the shared modeler policy with Codex's explicit routing gate."""
    modeler_prompt = (
        (workspace_root / "prompts" / "openstudio_agent.md")
        .read_text(encoding="utf-8")
        .strip()
    )
    return (
        f"{AGENTS_GENERATED_START}\n"
        "# OpenStudio AI Modeler Policy\n\n"
        "For every OpenStudio request, first load `openstudio-modeling-orchestrator`, "
        "then load the specialized OpenStudio skill that it routes to before taking "
        "action. This applies even when the user asks in plain language rather than "
        "naming a skill.\n\n"
        f"{modeler_prompt}\n"
        f"{AGENTS_GENERATED_END}\n"
    )


def _planned_export_files(
    export_root: Path,
    plugin_dir: Path,
    marketplace_path: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
    runtime_mode: str,
) -> list[Path]:
    """Return the files that `export_plugin` would create."""
    files = [
        marketplace_path,
        export_root / "INSTALL.md",
        plugin_dir / ".codex-plugin" / "plugin.json",
        plugin_dir / "assets" / "openstudio-ai-icon.png",
        plugin_dir / ".mcp.json",
        plugin_dir / "README.md",
        plugin_dir / "CONNECTORS.md",
    ]
    if runtime_mode == "marketplace":
        files.extend(
            plugin_dir / "skills" / skill_name / "SKILL.md"
            for skill_name in _marketplace_setup_skill_docs()
        )
    files.extend(
        export.target
        for export in skill_exports_for_host(workspace_root, plugin_dir, "codex")
    )
    files.extend(
        export.target
        for export in reference_exports_for_host(workspace_root, plugin_dir, "codex")
    )
    return sorted(files)


def _write_plugin_package(
    plugin_dir: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
    runtime_mode: str,
) -> None:
    """Materialize the Codex plugin package on disk."""
    (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "assets").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "skills").mkdir(parents=True, exist_ok=True)

    shutil.copy2(PLUGIN_ICON_PATH, plugin_dir / "assets" / "openstudio-ai-icon.png")

    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        _render_plugin_json(),
        encoding="utf-8",
    )
    (plugin_dir / ".mcp.json").write_text(
        _render_mcp_config(workspace_root, runtime_mode), encoding="utf-8"
    )
    (plugin_dir / "README.md").write_text(
        _render_plugin_readme(plan, workspace_root, runtime_mode), encoding="utf-8"
    )
    (plugin_dir / "CONNECTORS.md").write_text(
        _render_connectors_doc(workspace_root, runtime_mode), encoding="utf-8"
    )

    if runtime_mode == "marketplace":
        for skill_name, content in _marketplace_setup_skill_docs().items():
            target_dir = plugin_dir / "skills" / skill_name
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "SKILL.md").write_text(content, encoding="utf-8")

    for skill in skill_exports_for_host(workspace_root, plugin_dir, "codex"):
        target_dir = skill.target.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        skill.target.write_text(
            _render_exported_skill(skill.source, skill.skill),
            encoding="utf-8",
        )

    _write_skill_references(plugin_dir / "skills", workspace_root)


def _render_plugin_json() -> str:
    """Render Codex `.codex-plugin/plugin.json` with validation-required metadata."""
    return (
        json.dumps(
            {
                "name": DEFAULT_PLUGIN_NAME,
                "version": package_version(),
                "description": (
                    "OpenStudio AI harness for OpenStudio model editing, simulation, "
                    "results, SDK lookup, and reusable workflow skills."
                ),
                "author": {
                    "name": "OpenStudio AI",
                },
                "license": "BSD-3-Clause",
                "keywords": [
                    "openstudio",
                    "building-energy-modeling",
                    "mcp",
                    "simulation",
                ],
                "skills": "./skills/",
                "mcpServers": "./.mcp.json",
                "interface": {
                    "displayName": "OpenStudio AI",
                    "shortDescription": "OpenStudio modeling, simulation, SDK lookup, and workflow skills.",
                    "longDescription": (
                        "OpenStudio AI packages MCP tools, reusable skills, reviewed knowledge, "
                        "and blackboard contracts for building-energy modeling workflows."
                    ),
                    "developerName": "OpenStudio AI",
                    "category": "Engineering",
                    "capabilities": ["MCP", "Skills", "Workflow Automation"],
                    "defaultPrompt": [
                        "Inspect this OpenStudio model.",
                        "Add a VAV reheat system.",
                        "Run simulation and summarize results.",
                    ],
                    "brandColor": "#2563EB",
                    "composerIcon": "./assets/openstudio-ai-icon.png",
                    "logo": "./assets/openstudio-ai-icon.png",
                },
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
    )


def _render_mcp_config(workspace_root: Path, runtime_mode: str) -> str:
    """Render Codex MCP config for the selected runtime mode."""
    return (
        json.dumps(
            {
                "mcpServers": {
                    SERVER_NAME: _mcp_server_config(workspace_root, runtime_mode)
                }
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
    )


def _mcp_server_config(workspace_root: Path, runtime_mode: str) -> dict[str, object]:
    """Return the host MCP server config for local, installed, or marketplace mode."""
    if runtime_mode == "local":
        return {
            "command": sys.executable,
            "args": [
                "-m",
                "openstudio_ai_mcp.server",
                "--transport",
                "stdio",
                "--workspace-root",
                str(workspace_root / ".openstudio_ai_mcp_workspace"),
            ],
            "env": {
                "PYTHONPATH": str(workspace_root),
                "OPENSTUDIO_AI_ROOT": str(workspace_root),
                **plugin_mcp_environment(),
            },
        }
    if runtime_mode == "marketplace":
        return marketplace_mcp_server_config(plugin_mcp_environment())
    if runtime_mode == "installed":
        return {
            "command": "openstudio-ai-mcp",
            "args": ["--transport", "stdio"],
            "env": plugin_mcp_environment(),
        }
    raise ValueError(f"Unsupported runtime mode: {runtime_mode}")


def _render_marketplace_json(plugin_name: str) -> str:
    """Render a repo-local Codex marketplace manifest."""
    return (
        json.dumps(
            {
                "name": MARKETPLACE_NAME,
                "interface": {
                    "displayName": "OpenStudio AI Local",
                },
                "plugins": [
                    {
                        "name": plugin_name,
                        "source": {
                            "source": "local",
                            "path": f"./plugins/{plugin_name}",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Engineering",
                    }
                ],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
    )


def _render_install_doc(
    export_root: Path,
    marketplace_path: Path,
    plugin_name: str,
    runtime_mode: str,
) -> str:
    """Render installation instructions for the exported Codex plugin."""
    export_ref = "<path-to-this-marketplace-folder>"
    validate_ref = "<path-to-this-plugin-json>"
    install_codex = "openstudio-ai install codex --target-dir <path-to-project>"
    if runtime_mode == "marketplace":
        install_codex = runtime_uvx_command(
            "openstudio-ai", "install", "codex", "--target-dir", "<path-to-project>"
        )
    if runtime_mode != "marketplace":
        export_ref = str(export_root)
        validate_ref = str(
            export_root / "plugins" / plugin_name / ".codex-plugin" / "plugin.json"
        )
    return (
        "# Install OpenStudio AI In Codex\n\n"
        "This export is a Codex marketplace containing the OpenStudio AI plugin.\n\n"
        "## 1. Validate The Plugin\n\n"
        "From the OpenStudio AI harness repository:\n\n"
        "```bash\n"
        f"python -m json.tool {validate_ref}\n"
        "```\n\n"
        "## 2. Add The Local Marketplace\n\n"
        "Use this marketplace file with Codex:\n\n"
        "```bash\n"
        f"codex plugin marketplace add {export_ref}\n"
        "```\n\n"
        "## 3. Install Or View The Plugin\n\n"
        "Open the Codex plugin UI and install `openstudio-ai` from `openstudio-ai-local`.\n\n"
        "## 4. Add The Modeler Policy To A Project\n\n"
        "Codex plugins load skills and MCP tools, but they do not activate a plugin "
        "agent prompt as the main thread. In each project where plain-language "
        "OpenStudio requests should consistently enter the workflow router, install "
        "the managed OpenStudio block into `AGENTS.md`:\n\n"
        "```bash\n"
        f"{install_codex}\n"
        "```\n\n"
        "Use `--dry-run` to preview. If the project already has an unmanaged "
        "`AGENTS.md`, use `--force` only after reviewing the proposed append. "
        "Later runs update only the marked OpenStudio block.\n\n"
        "## Runtime Setup\n\n"
        "After installation, invoke the setup skill with `$setup-openstudio-ai` (or ask "
        "Codex in plain language to set up OpenStudio AI). `/setup-openstudio-ai` is not "
        "a Codex CLI skill command. The setup skill checks uv, prepares the pinned "
        "runtime, and explains any missing installation steps in "
        "energy-modeler language.\n"
    )


def _render_plugin_readme(
    plan: HostLaunchPlan, workspace_root: Path, runtime_mode: str
) -> str:
    """Render the README shipped with the Codex plugin."""
    skill_names = "\n".join(
        f"- `{skill}`" for skill in skill_ids_for_host(workspace_root, "codex")
    )
    return (
        "# OpenStudio AI\n\n"
        "OpenStudio AI is a Codex plugin package for building-energy modeling workflows "
        "using OpenStudio, MCP tools, reusable skills, and reviewed knowledge.\n\n"
        "## What It Includes\n\n"
        "- `.mcp.json`: registers the `openstudio_ai` MCP server.\n"
        "- `skills/`: Codex-native workflows for orchestration, setup, model editing, "
        "simulation, results, learning capture, and HVAC workflows.\n"
        "- `skills/*/references/`: reviewed SDK context packs, prompt contracts, "
        "blackboard schemas, and learning schemas used by the owning skills.\n"
        "- `skills/setup-openstudio-ai/`: marketplace runtime setup through uv.\n\n"
        "## Skills\n\n"
        f"{skill_names}\n\n"
        "## Runtime Note\n\n"
        f"Runtime mode: `{runtime_mode}`.\n\n"
        "In `local` mode, this plugin references a source checkout. In `installed` "
        "mode, it expects the `openstudio-ai-mcp` command to be available on the "
        "user's machine. In `marketplace` mode, it launches the matching runtime "
        "release through `uvx`.\n"
    )


def _render_connectors_doc(workspace_root: Path, runtime_mode: str) -> str:
    """Render connector documentation for the Codex plugin package."""
    if runtime_mode == "local":
        runtime_text = (
            "The current `.mcp.json` points to the local checkout:\n\n"
            f"- `{workspace_root}`\n"
        )
    elif runtime_mode == "marketplace":
        runtime_text = (
            "The current `.mcp.json` launches the pinned runtime through uv:\n\n"
            f"- `{runtime_uvx_command('openstudio-ai-mcp', '--transport', 'stdio')}`\n"
        )
    else:
        runtime_text = (
            "The current `.mcp.json` points to the installed runtime command:\n\n"
            "- `openstudio-ai-mcp --transport stdio`\n"
        )
    return (
        "# OpenStudio AI Connectors\n\n"
        "This plugin uses one local MCP server.\n\n"
        "| Connector | Type | Purpose |\n"
        "| --- | --- | --- |\n"
        "| `openstudio_ai` | local stdio MCP | OpenStudio model lifecycle, simulation, "
        "results, approved measures, and SDK documentation lookup |\n\n"
        f"{runtime_text}"
    )


def _marketplace_setup_skill_docs() -> dict[str, str]:
    """Return marketplace setup skills for no-code runtime onboarding."""
    configure = runtime_uvx_command(
        "openstudio-ai", "configure-openstudio", "--path", "<confirmed-executable>"
    )
    doctor = runtime_doctor_command()
    routing_preview = runtime_uvx_command(
        "openstudio-ai", "install", "codex", "--target-dir", ".", "--dry-run", "--force"
    )
    routing = runtime_uvx_command(
        "openstudio-ai", "install", "codex", "--target-dir", ".", "--force"
    )
    return {
        "setup-openstudio-ai": _skill_markdown(
            name="setup-openstudio-ai",
            description="Check and prepare the OpenStudio AI runtime for energy modeling.",
            body=(
                "# Setup OpenStudio AI\n\n"
                "Help the user get OpenStudio AI ready without assuming programming experience.\n\n"
                "1. Explain that OpenStudio AI runs its runtime through `uv`, which "
                "downloads the exact runtime release this plugin was built for, "
                "including its own Python. The user does not need to choose a Python. "
                "Also explain that setup includes adding or updating the OpenStudio AI "
                "marked block in the current project's `AGENTS.md`; it preserves all "
                "unrelated project instructions.\n"
                "2. Check whether uv is available by running `uvx --version`. If it is "
                "missing, ask before installing it. If `pipx --version` works, prefer "
                "`pipx install uv`; otherwise offer an installer from "
                "https://docs.astral.sh/uv/getting-started/installation/. Use pipx only "
                "to install uv, never to install the OpenStudio AI runtime.\n"
                f"3. {prepare_runtime_guidance('Codex')}"
                f"4. Run the doctor: `{doctor}`.\n"
                "5. Treat `core_ready: true` from the doctor as the only successful core "
                "setup result. If OpenStudio is missing, perform read-only platform discovery, "
                "show the candidate executable to the user, and after approval run "
                f"`{configure}`. Then "
                "restart Codex and rerun doctor. Do not edit a versioned plugin cache file.\n"
                "6. Review the doctor's optional `nlr_openstudio` capability. NLR OpenStudio-MCP "
                "is optional: a missing Docker installation or unconfigured NLR must not block "
                "core readiness. If Docker is available and the user wants NLR, offer its "
                "Docker Quick Start without installing it automatically: "
                "https://pnnl.github.io/openstudio-ai-plugins/#quick-start. Explain that "
                "Docker Desktop must be installed and running, then the user follows that "
                "page to configure the MCP server as `openstudio-mcp` and restarts Codex.\n"
                f"7. {doctor_triage_guidance()}"
                "8. If `uvx` works in a terminal but the MCP server still cannot start, "
                "diagnose command discovery before editing plugin files: check whether the "
                "directory containing `uvx` is on the PATH used to launch Codex. Keep "
                "`.mcp.json` set to the portable `uvx` launch; do not replace it with an "
                "absolute path. After the user approves a PATH update, restart Codex from "
                "that environment.\n"
                "9. If this is intentionally a repository checkout with a project virtual "
                "environment, explain that it is local development: re-export with "
                "`--runtime-mode local` instead of modifying a marketplace export.\n"
                f"10. {offline_guidance('Codex')}"
                "11. If setup prepared or rebuilt the runtime, or the MCP server had "
                "failed to connect, tell the user to restart Codex or reconnect the failed "
                "MCP server. Codex discovers MCP tools only when it starts the server, so a "
                "new tool cannot appear in the current session.\n"
                "12. Complete project routing as a required part of setup. Preview the managed "
                f"project guidance with `{routing_preview}`, then run `{routing}`. "
                "This creates `AGENTS.md` when absent, updates only the OpenStudio AI marked "
                "block when it already exists, or appends that block to an unmanaged file "
                "without replacing existing instructions. Do not present this as a separate "
                "optional setup process.\n"
                "13. Summarize core readiness separately from optional capabilities, then report "
                "model loading, HVAC workflow support, simulation, "
                "results, SDK lookup, workflow state tracking, and project routing.\n"
            ),
        ),
        "doctor-openstudio-ai": _skill_markdown(
            name="doctor-openstudio-ai",
            description="Diagnose OpenStudio AI runtime readiness.",
            body=(
                "# Doctor OpenStudio AI\n\n"
                f"Run `{doctor}`. If `uvx` is missing, follow the setup skill. "
                f"{doctor_triage_guidance()}"
                "Explain "
                "missing uv, missing runtime, missing OpenStudio, or path problems as "
                "setup items, not programming failures.\n"
            ),
        ),
        "repair-openstudio-ai": _skill_markdown(
            name="repair-openstudio-ai",
            description="Guide non-destructive repair of the OpenStudio AI runtime.",
            body=(
                "# Repair OpenStudio AI\n\n"
                "First run the doctor command. "
                f"{doctor_triage_guidance()}"
                "After preparing or rebuilding the runtime, restart Codex or reconnect "
                "the MCP server before retrying. Do not "
                "delete user models, simulation outputs, or project files. If `uvx` works "
                "in a terminal but Codex cannot find it, follow the "
                "setup skill's PATH diagnosis. Do not hard-code an absolute path "
                "into a marketplace `.mcp.json`. Describe each repair step in plain language "
                "for an energy modeler.\n"
            ),
        ),
    }


def _skill_markdown(*, name: str, description: str, body: str) -> str:
    """Render a Codex skill file with YAML frontmatter."""
    return "---\n" f"name: {name}\n" f"description: {description}\n" "---\n\n" f"{body}"


def _render_exported_skill(skill_path: Path, skill_name: str) -> str:
    """Render a source skill with Codex-plugin frontmatter naming."""
    return _rewrite_skill_frontmatter_name(
        skill_path.read_text(encoding="utf-8"), skill_name
    )


def _rewrite_skill_frontmatter_name(content: str, skill_name: str) -> str:
    """Keep Codex skill frontmatter aligned with the exported folder name."""
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content

    header = content[4:end]
    body = content[end:]
    lines = header.splitlines()
    replaced = False
    rewritten: list[str] = []
    for line in lines:
        if line.startswith("name:"):
            rewritten.append(f"name: {skill_name}")
            replaced = True
        else:
            rewritten.append(line)
    if not replaced:
        rewritten.insert(0, f"name: {skill_name}")
    return "---\n" + "\n".join(rewritten) + body


def _write_skill_references(skills_dir: Path, workspace_root: Path) -> None:
    """Place supporting files inside the Codex skills that use them."""
    plugin_dir = skills_dir.parent
    for export in reference_exports_for_host(workspace_root, plugin_dir, "codex"):
        _copy_reference_file(export.source, export.target)


def _copy_reference_file(source: Path, target: Path) -> None:
    """Copy a Codex reference file without top-level YAML agent-like metadata."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() != ".md":
        shutil.copy2(source, target)
        return
    target.write_text(
        _strip_yaml_frontmatter(source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )


def _strip_yaml_frontmatter(content: str) -> str:
    """Remove a leading YAML frontmatter block from Markdown reference docs."""
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    remainder = content[end + len("\n---") :]
    return remainder.lstrip("\n")


def _default_workspace_root() -> Path:
    """Return the OpenStudio AI example root from this adapter module."""
    return Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for Codex plugin and project guidance operations."""
    parser = argparse.ArgumentParser(
        description="Export the OpenStudio AI harness as a Codex plugin."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser(
        "install", help="Install managed OpenStudio guidance into a Codex AGENTS.md."
    )
    install.add_argument(
        "--target-dir",
        type=Path,
        required=True,
        help="Codex project directory containing AGENTS.md.",
    )
    install.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_workspace_root(),
        help="OpenStudio AI harness root containing the shared modeler policy.",
    )
    install.add_argument(
        "--dry-run", action="store_true", help="Preview guidance without writing it."
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Append the managed block to an existing unmanaged AGENTS.md.",
    )

    export = subparsers.add_parser(
        "export-plugin", help="Export a Codex plugin and local marketplace."
    )
    export.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where the local marketplace and plugin folder should be created.",
    )
    export.add_argument(
        "--plugin-name",
        default=DEFAULT_PLUGIN_NAME,
        help="Plugin folder name and install name.",
    )
    export.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_workspace_root(),
        help="OpenStudio AI harness root.",
    )
    export.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview package files without writing them.",
    )
    export.add_argument(
        "--force", action="store_true", help="Replace an existing plugin folder."
    )
    export.add_argument(
        "--runtime-mode",
        choices=sorted(RUNTIME_MODES),
        default="local",
        help="Runtime connection mode for generated MCP config and setup assets.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for Codex adapter operations."""
    args = _parse_args()
    if args.command == "install":
        adapter = CodexAdapter(
            config=HostAdapterConfig(
                host_name="codex", workspace_root=args.workspace_root
            )
        )
        result = adapter.install(
            args.target_dir, dry_run=args.dry_run, force=args.force
        )
        mode = "Would write" if result.dry_run else "Wrote"
        for action in result.actions:
            print(f"{mode} {action.path} ({action.action})")
            if result.dry_run:
                print(action.content)
        return 0
    if args.command == "export-plugin":
        adapter = CodexAdapter(
            config=HostAdapterConfig(
                host_name="codex",
                workspace_root=args.workspace_root,
                runtime_mode=args.runtime_mode,
            )
        )
        result = adapter.export_plugin(
            args.output_dir,
            plugin_name=args.plugin_name,
            dry_run=args.dry_run,
            force=args.force,
        )
        mode = "Would export" if result.dry_run else "Exported"
        print(f"{mode} marketplace: {result.marketplace_path}")
        print(f"{mode} plugin: {result.plugin_dir}")
        for path in result.files:
            print(f"- {path}")
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
