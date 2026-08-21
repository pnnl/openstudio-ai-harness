from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from adapters.base import OpenStudioAiHostAdapter
from adapters.contracts import RUNTIME_MODES, HostAdapterConfig, HostLaunchPlan
from adapters.runtime_helpers import write_runtime_helpers
from harness.asset_manifest import (
    agent_source_for_host,
    reference_exports_for_host,
    skill_exports_for_host,
    skill_ids_for_host,
    skill_sources_for_host,
)
from harness.registry import discover_harness_assets
from openstudio_mcp.compatibility import package_version, plugin_mcp_environment

GENERATED_START = "<!-- BEGIN OPENSTUDIO_AI_HARNESS -->"
GENERATED_END = "<!-- END OPENSTUDIO_AI_HARNESS -->"
SERVER_NAME = "openstudio_ai"
DEFAULT_PLUGIN_NAME = "openstudio-ai"
MARKETPLACE_NAME = "openstudio-ai-local"


@dataclass(frozen=True)
class InstallAction:
    """A single file write planned by the project-level Claude install path."""

    path: Path
    action: str
    content: str


@dataclass(frozen=True)
class InstallResult:
    """Result for project-level installation into an existing Claude Code workspace."""

    dry_run: bool
    target_dir: Path
    actions: list[InstallAction]


@dataclass(frozen=True)
class PluginExportResult:
    """Result for exporting a plugin-style package for Claude hosts."""

    dry_run: bool
    marketplace_dir: Path
    plugin_dir: Path
    files: list[Path]


class ClaudeCodeAdapter(OpenStudioAiHostAdapter):
    """Adapter contract for installing OpenStudio AI into Claude Code-style hosts."""

    def build_launch_plan(self) -> HostLaunchPlan:
        """Resolve the host-facing assets from the OpenStudio AI harness registry."""
        assets = discover_harness_assets(self.config.workspace_root)
        return HostLaunchPlan(
            host_name="claude_code",
            system_prompt_files=assets.prompt_contracts,
            skill_paths=skill_sources_for_host(self.config.workspace_root, "claude"),
            mcp_entrypoint=assets.mcp_entrypoint,
            blackboard_schema=assets.blackboard_schema,
            learning_event_log=assets.learning_event_log,
            notes=[
                "Map harness files into the host's project instructions and MCP config."
            ],
        )

    def build_install_actions(
        self, target_dir: Path, *, force: bool = False
    ) -> list[InstallAction]:
        """Plan project-local Claude Code files without writing them.

        This is the development/debug path. The distributable path is
        `export_plugin`, which keeps skills and knowledge in separate plugin
        package folders instead of flattening them into CLAUDE.md.
        """
        target_dir = target_dir.resolve()
        plan = self.build_launch_plan()
        actions = [
            InstallAction(
                path=target_dir / ".mcp.json",
                action="write_mcp_config",
                content=_render_mcp_config(
                    existing_path=target_dir / ".mcp.json",
                    plan=plan,
                    workspace_root=self.config.workspace_root.resolve(),
                    runtime_mode=self.config.runtime_mode,
                ),
            ),
            InstallAction(
                path=target_dir / ".claude" / "CLAUDE.md",
                action="write_project_instructions",
                content=_render_claude_instructions(
                    existing_path=target_dir / ".claude" / "CLAUDE.md",
                    plan=plan,
                    workspace_root=self.config.workspace_root.resolve(),
                    force=force,
                ),
            ),
        ]
        return actions

    def install(
        self, target_dir: Path, *, dry_run: bool = True, force: bool = False
    ) -> InstallResult:
        """Write or preview project-local Claude Code configuration files."""
        actions = self.build_install_actions(target_dir, force=force)
        if not dry_run:
            for action in actions:
                action.path.parent.mkdir(parents=True, exist_ok=True)
                action.path.write_text(action.content, encoding="utf-8")
        return InstallResult(
            dry_run=dry_run, target_dir=target_dir.resolve(), actions=actions
        )

    def export_plugin(
        self,
        output_dir: Path,
        *,
        plugin_name: str = DEFAULT_PLUGIN_NAME,
        dry_run: bool = True,
        force: bool = False,
    ) -> PluginExportResult:
        """Export a Claude plugin-style package.

        The exported package follows Claude Code's native plugin layout:
        metadata, MCP config, agents, monitors, bin scripts, and folder-per-skill
        packages with supporting reference files kept inside the relevant skill.
        """
        workspace_root = self.config.workspace_root.resolve()
        marketplace_dir = output_dir.resolve()
        plugin_dir = (marketplace_dir / plugin_name).resolve()
        plan = self.build_launch_plan()
        runtime_mode = self.config.runtime_mode
        files = _planned_export_files(
            marketplace_dir, plugin_dir, plan, workspace_root, runtime_mode
        )

        if dry_run:
            return PluginExportResult(
                dry_run=True,
                marketplace_dir=marketplace_dir,
                plugin_dir=plugin_dir,
                files=files,
            )

        if plugin_dir.exists():
            if not force:
                raise FileExistsError(
                    f"{plugin_dir} already exists. Use --force to replace it."
                )
            shutil.rmtree(plugin_dir)

        (marketplace_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (marketplace_dir / ".claude-plugin" / "marketplace.json").write_text(
            _render_marketplace_json(plugin_name),
            encoding="utf-8",
        )
        (marketplace_dir / "INSTALL.md").write_text(
            _render_install_doc(marketplace_dir, plugin_name, runtime_mode),
            encoding="utf-8",
        )
        _write_plugin_package(plugin_dir, plan, workspace_root, runtime_mode)
        return PluginExportResult(
            dry_run=False,
            marketplace_dir=marketplace_dir,
            plugin_dir=plugin_dir,
            files=files,
        )


def _render_mcp_config(
    existing_path: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
    runtime_mode: str,
) -> str:
    """Render project-level `.mcp.json` while preserving unrelated servers."""
    existing: dict[str, object] = {}
    if existing_path.exists():
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
    mcp_servers = (
        dict(existing.get("mcpServers", {}))
        if isinstance(existing.get("mcpServers"), dict)
        else {}
    )
    mcp_servers[SERVER_NAME] = _mcp_server_config(workspace_root, runtime_mode)
    existing["mcpServers"] = mcp_servers
    return json.dumps(existing, indent=2, ensure_ascii=True) + "\n"


def _render_plugin_mcp_config(workspace_root: Path, runtime_mode: str) -> str:
    """Render plugin `.mcp.json` for the selected runtime mode."""
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
                "openstudio_mcp.server",
                "--transport",
                "stdio",
                "--workspace-root",
                str(workspace_root / ".openstudio_mcp_workspace"),
            ],
            "env": {
                "PYTHONPATH": str(workspace_root),
                "OPENSTUDIO_AI_ROOT": str(workspace_root),
                **plugin_mcp_environment(),
            },
        }
    if runtime_mode in {"installed", "marketplace"}:
        return {
            "command": "openstudio-ai-mcp",
            "args": ["--transport", "stdio"],
            "env": plugin_mcp_environment(),
        }
    raise ValueError(f"Unsupported runtime mode: {runtime_mode}")


def _render_claude_instructions(
    existing_path: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
    *,
    force: bool,
) -> str:
    """Render or update a project-level CLAUDE.md block.

    Generated markers let the adapter refresh its own block without rewriting
    hand-authored project instructions. Unmanaged files require `--force`.
    """
    generated = _generated_instruction_block(plan, workspace_root)
    if not existing_path.exists():
        return generated

    existing = existing_path.read_text(encoding="utf-8")
    if GENERATED_START in existing and GENERATED_END in existing:
        before, rest = existing.split(GENERATED_START, 1)
        _, after = rest.split(GENERATED_END, 1)
        return before.rstrip() + "\n\n" + generated + "\n" + after.lstrip()

    if not force:
        raise FileExistsError(
            f"{existing_path} already exists and is not managed by OpenStudio AI. "
            "Use --force to append the generated OpenStudio AI block."
        )

    return existing.rstrip() + "\n\n" + generated


def _generated_instruction_block(plan: HostLaunchPlan, workspace_root: Path) -> str:
    """Render the minimal project-install instruction block.

    This block is deliberately only a pointer map. It is not the plugin export
    format and should not contain full skill or knowledge-base content.
    """
    prompt_lines = "\n".join(f"- `{path}`" for path in plan.system_prompt_files)
    skill_lines = "\n".join(f"- `{path}`" for path in plan.skill_paths)
    return (
        f"{GENERATED_START}\n"
        "# OpenStudio AI Harness\n\n"
        "Use OpenStudio AI for OpenStudio model inspection, model editing, simulation, "
        "result retrieval, SDK lookup, and workflow skill guidance.\n\n"
        "## Runtime Boundaries\n\n"
        "- Use the `openstudio_ai` MCP server for model lifecycle, simulation, results, "
        "approved measures, and SDK documentation lookup.\n"
        "- Use the listed OpenStudio AI skill files as workflow guidance.\n"
        "- Treat the blackboard schema as the source of truth for long-running workflow state.\n"
        "- Learning skills support candidate drafting only; they do not persist candidate assets. "
        "Trusted assets require review and eval validation.\n\n"
        "## Harness Paths\n\n"
        f"- Root: `{workspace_root}`\n"
        f"- MCP entrypoint: `{plan.mcp_entrypoint}`\n"
        f"- Blackboard schema: `{plan.blackboard_schema}`\n"
        f"- Learning event log: `{plan.learning_event_log}`\n\n"
        "## Prompt Contracts\n\n"
        f"{prompt_lines}\n\n"
        "## Runtime Skills\n\n"
        f"{skill_lines}\n"
        f"{GENERATED_END}\n"
    )


def _planned_export_files(
    marketplace_dir: Path,
    plugin_dir: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
    runtime_mode: str,
) -> list[Path]:
    """Return the marketplace and plugin files that `export_plugin` would create.

    Dry-run uses this list for review, while tests use it to keep the package
    contract stable.
    """
    files = [
        marketplace_dir / ".claude-plugin" / "marketplace.json",
        marketplace_dir / "INSTALL.md",
        plugin_dir / ".claude-plugin" / "plugin.json",
        plugin_dir / ".mcp.json",
        plugin_dir / "README.md",
        plugin_dir / "CONNECTORS.md",
        plugin_dir / "settings.json",
        plugin_dir / "agents" / "openstudio-modeler.md",
        plugin_dir / "monitors" / "monitors.json",
        plugin_dir / "bin" / "openstudio-ai-learning-monitor",
    ]
    if runtime_mode == "marketplace":
        files.extend(
            [
                plugin_dir / "skills" / "setup-openstudio-ai" / "SKILL.md",
                plugin_dir
                / "skills"
                / "setup-openstudio-ai"
                / "scripts"
                / "install_runtime.py",
                plugin_dir
                / "skills"
                / "setup-openstudio-ai"
                / "scripts"
                / "doctor_runtime.py",
                plugin_dir / "skills" / "doctor-openstudio-ai" / "SKILL.md",
                plugin_dir / "skills" / "repair-openstudio-ai" / "SKILL.md",
            ]
        )
    files.extend(
        export.target
        for export in skill_exports_for_host(workspace_root, plugin_dir, "claude")
    )
    files.extend(
        export.target
        for export in reference_exports_for_host(workspace_root, plugin_dir, "claude")
    )
    return sorted(files)


def _render_marketplace_json(plugin_name: str) -> str:
    """Render a local marketplace manifest that points at the exported plugin."""
    return (
        json.dumps(
            {
                "$schema": "https://json.schemastore.org/claude-code-marketplace.json",
                "name": MARKETPLACE_NAME,
                "version": package_version(),
                "description": "Local marketplace for the OpenStudio AI Claude plugin.",
                "owner": {
                    "name": "OpenStudio AI",
                },
                "plugins": [
                    {
                        "name": plugin_name,
                        "description": (
                            "OpenStudio AI harness for OpenStudio model editing, simulation, "
                            "results, SDK lookup, and reusable workflow skills."
                        ),
                        "version": package_version(),
                        "source": f"./{plugin_name}",
                        "category": "engineering",
                    }
                ],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
    )


def _render_install_doc(
    marketplace_dir: Path, plugin_name: str, runtime_mode: str
) -> str:
    """Render install instructions for using the exported package in Claude Code."""
    marketplace_ref = "this exported marketplace folder"
    validation_command = "claude plugin validate <path-to-this-marketplace-folder>"
    marketplace_command = "/plugin marketplace add <path-to-this-marketplace-folder>"
    if runtime_mode != "marketplace":
        marketplace_ref = str(marketplace_dir)
        validation_command = f"claude plugin validate {marketplace_dir}"
        marketplace_command = f"/plugin marketplace add {marketplace_dir}"
    return (
        "# Install OpenStudio AI In Claude Code\n\n"
        f"This export is a Claude Code marketplace containing the OpenStudio AI plugin. Use {marketplace_ref}.\n\n"
        "## 1. Validate The Export\n\n"
        "From the OpenStudio AI harness repository:\n\n"
        "```bash\n"
        f"{validation_command}\n"
        "```\n\n"
        "## 2. Add The Local Marketplace\n\n"
        "Open Claude Code in the target project and run:\n\n"
        "```text\n"
        f"{marketplace_command}\n"
        "```\n\n"
        "## 3. Install The Plugin\n\n"
        "Still inside Claude Code, run:\n\n"
        "```text\n"
        f"/plugin install {plugin_name}@{MARKETPLACE_NAME}\n"
        "```\n\n"
        "If Claude Code asks for scope, choose local or project scope for testing.\n\n"
        "## 4. Reload Plugins\n\n"
        "```text\n"
        "/reload-plugins\n"
        "```\n\n"
        "## 5. Try The Plugin\n\n"
        "Use one of the namespaced skills:\n\n"
        "```text\n"
        f"/{plugin_name}:add-vav-reheat\n"
        f"/{plugin_name}:simulate\n"
        f"/{plugin_name}:query-results\n"
        "```\n\n"
        "The plugin also contributes the OpenStudio modeler agent and an `openstudio_ai` MCP server.\n\n"
        "## Runtime Setup\n\n"
        "After installation, run the setup skill:\n\n"
        "```text\n"
        f"/{plugin_name}:setup-openstudio-ai\n"
        "```\n\n"
        "The setup skill checks Python, checks `openstudio-ai-mcp`, and explains any "
        "missing installation steps in energy-modeler language.\n"
    )


def _write_plugin_package(
    plugin_dir: Path,
    plan: HostLaunchPlan,
    workspace_root: Path,
    runtime_mode: str,
) -> None:
    """Materialize the plugin package on disk."""
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "agents").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "bin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "monitors").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "skills").mkdir(parents=True, exist_ok=True)

    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "openstudio-ai",
                "displayName": "OpenStudio AI",
                "version": package_version(),
                "description": (
                    "OpenStudio AI harness for model editing, simulation, results, "
                    "SDK lookup, and reusable building-energy workflow skills."
                ),
                "author": {"name": "OpenStudio AI"},
                "keywords": [
                    "openstudio",
                    "building-energy-modeling",
                    "mcp",
                    "simulation",
                ],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / ".mcp.json").write_text(
        _render_plugin_mcp_config(workspace_root, runtime_mode),
        encoding="utf-8",
    )
    (plugin_dir / "settings.json").write_text(
        json.dumps({"agent": "openstudio-modeler"}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "README.md").write_text(
        _render_plugin_readme(plan, workspace_root, runtime_mode), encoding="utf-8"
    )
    (plugin_dir / "CONNECTORS.md").write_text(
        _render_connectors_doc(workspace_root, runtime_mode),
        encoding="utf-8",
    )
    (plugin_dir / "agents" / "openstudio-modeler.md").write_text(
        _render_openstudio_modeler_agent(workspace_root),
        encoding="utf-8",
    )
    (plugin_dir / "monitors" / "monitors.json").write_text(
        _render_learning_monitor_config(),
        encoding="utf-8",
    )
    monitor_script = plugin_dir / "bin" / "openstudio-ai-learning-monitor"
    monitor_script.write_text(_learning_monitor_script(), encoding="utf-8")
    monitor_script.chmod(0o755)

    for skill in skill_exports_for_host(workspace_root, plugin_dir, "claude"):
        target_dir = skill.target.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        skill.target.write_text(
            _render_exported_skill(skill.source, skill.skill),
            encoding="utf-8",
        )

    _write_marketplace_setup_skills(plugin_dir / "skills", runtime_mode)
    _write_skill_references(plugin_dir / "skills", workspace_root)

    if runtime_mode == "marketplace":
        setup_scripts_dir = plugin_dir / "skills" / "setup-openstudio-ai" / "scripts"
        _write_installer_assets(setup_scripts_dir)


def _render_exported_skill(skill_path: Path, skill_name: str) -> str:
    """Render a source skill with Claude-plugin reference navigation appended."""
    content = _rewrite_skill_frontmatter_name(
        skill_path.read_text(encoding="utf-8"), skill_name
    )
    references = _skill_reference_notes(skill_name)
    if not references:
        return content
    return content.rstrip() + "\n\n" + references + "\n"


def _rewrite_skill_frontmatter_name(content: str, skill_name: str) -> str:
    """Keep Claude skill frontmatter aligned with the exported folder name."""
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


def _skill_reference_notes(skill_name: str) -> str:
    if skill_name == "openstudio-sdk-model-editor":
        return (
            "## Claude Code Supporting Files\n\n"
            "Load these files only when needed for the current SDK task:\n\n"
            "- `references/openstudio_sdk_recipes.md`: SDK context-pack routing "
            "and non-negotiable scripting rules.\n"
            "- `references/sdk_wiki/`: detailed OpenStudio SDK context packs for "
            "geometry, constructions, schedules, spaces/zones/loads, daylighting, "
            "HVAC, and simulation-result idioms.\n"
        )
    if skill_name == "openstudio-vav-reheat-system-creator":
        return (
            "## Claude Code Supporting Files\n\n"
            "For durable long-running workflow state, load "
            "`openstudio-workflow-state`. This VAV skill owns the VAV-specific "
            "phase order, required inputs, and child-skill routing only.\n"
        )
    if skill_name == "openstudio-workflow-state":
        return (
            "## Claude Code Supporting Files\n\n"
            "Load these workflow references when coordinating any long-running "
            "OpenStudio task:\n\n"
            "- `references/blackboard_contract.md`: MCP-owned blackboard usage rules.\n"
            "- `references/workflow_state.schema.json`: durable workflow-state shape.\n"
            "- `references/state_patch.schema.json`: child-skill patch shape.\n"
        )
    return ""


def _write_marketplace_setup_skills(skills_dir: Path, runtime_mode: str) -> None:
    """Write adapter-owned marketplace setup skills when needed."""
    if runtime_mode != "marketplace":
        return
    for skill_name, content in _marketplace_setup_skill_docs().items():
        target_dir = skills_dir / skill_name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "SKILL.md").write_text(content, encoding="utf-8")


def _marketplace_setup_skill_docs() -> dict[str, str]:
    return {
        "setup-openstudio-ai": _skill_markdown(
            name="setup-openstudio-ai",
            description="Check and prepare the OpenStudio AI runtime for energy modeling.",
            body=(
                "# Setup OpenStudio AI\n\n"
                "Help the user get OpenStudio AI ready without assuming programming "
                "experience.\n\n"
                "1. Explain that OpenStudio AI needs a local runtime command named "
                "`openstudio-ai-mcp` so the AI assistant can safely run OpenStudio "
                "tools.\n"
                "2. Check whether Python is available using `python --version`. If "
                "that fails, try `python3 --version`.\n"
                "3. Check whether `openstudio-ai-mcp` is available by running "
                "`openstudio-ai-mcp --help`.\n"
                "4. Run `python ${CLAUDE_SKILL_DIR}/scripts/doctor_runtime.py`. If "
                "`python` is unavailable, try "
                "`python3 ${CLAUDE_SKILL_DIR}/scripts/doctor_runtime.py`.\n"
                "5. Review the doctor's `nlr_openstudio` result. NLR OpenStudio-MCP is "
                "optional: OpenStudio AI works as it is without NLR, but a user who prefers "
                "it can select NLR as the core modeling backend. If NLR is not configured, "
                "offer its Docker Quick Start without installing it automatically: "
                "https://pnnl.github.io/openstudio-ai-plugins/#quick-start. Explain that "
                "Docker Desktop must be installed and running, then the user follows that "
                "page to configure the MCP server as `nlr_openstudio` and reloads Claude Code.\n"
                "6. If the runtime is missing, explain the issue in normal "
                "energy-modeler language and ask before running "
                "`python ${CLAUDE_SKILL_DIR}/scripts/install_runtime.py`.\n"
                "7. If installation succeeds but `openstudio-ai-mcp` is still missing, "
                "diagnose command discovery before editing plugin files. Run "
                '`python -c "import sys, sysconfig; print(sys.executable); '
                "print(sysconfig.get_path('scripts'))\"` (or `python3`), then check "
                "whether that scripts directory is on the PATH used to launch Claude Code. "
                "For a marketplace plugin, keep `.mcp.json` set to the portable command "
                "`openstudio-ai-mcp`; do not replace it with an absolute `.venv/bin` path. "
                "After the user approves a PATH update, restart Claude Code from that "
                "environment.\n"
                "8. If this is intentionally a repository checkout with a project virtual "
                "environment, explain that it is local development: re-export with "
                "`--runtime-mode local` instead of modifying a marketplace export.\n"
                "9. When `openstudio-ai` is available, run `openstudio-ai doctor`.\n"
                "10. If installation changed runtime command availability, tell the "
                "user to run `/reload-plugins` or reconnect the failed MCP server so "
                "Claude Code starts `openstudio-ai-mcp` again.\n"
                "11. Summarize readiness for model loading, HVAC workflow support, "
                "simulation, results, SDK lookup, and workflow state tracking.\n"
            ),
        ),
        "doctor-openstudio-ai": _skill_markdown(
            name="doctor-openstudio-ai",
            description="Diagnose OpenStudio AI runtime readiness.",
            body=(
                "# Doctor OpenStudio AI\n\n"
                "Run `python ${CLAUDE_SKILL_DIR}/../setup-openstudio-ai/scripts/"
                "doctor_runtime.py`, then run `openstudio-ai doctor` if the command "
                "exists. Explain missing Python, missing runtime, missing OpenStudio, "
                "or path problems as setup items, not programming failures.\n"
            ),
        ),
        "repair-openstudio-ai": _skill_markdown(
            name="repair-openstudio-ai",
            description="Guide non-destructive repair of the OpenStudio AI runtime.",
            body=(
                "# Repair OpenStudio AI\n\n"
                "First run the doctor skill. If the runtime is missing, ask for "
                "approval before running `python ${CLAUDE_SKILL_DIR}/../"
                "setup-openstudio-ai/scripts/install_runtime.py`. Do not delete user "
                "models, simulation outputs, or project files. If the installer found "
                "the command beside its Python but Claude cannot find it, follow the "
                "setup skill's PATH diagnosis. Do not hard-code a project virtualenv "
                "path into a marketplace `.mcp.json`. Describe each repair step in plain "
                "language for an energy modeler.\n"
            ),
        ),
    }


def _skill_markdown(name: str, description: str, body: str) -> str:
    return "---\n" f"name: {name}\n" f"description: {description}\n" "---\n\n" f"{body}"


def _write_skill_references(skills_dir: Path, workspace_root: Path) -> None:
    """Place supporting files inside the Claude skills that use them."""
    plugin_dir = skills_dir.parent
    for export in reference_exports_for_host(workspace_root, plugin_dir, "claude"):
        _copy_reference_file(export.source, export.target)


def _copy_reference_file(source: Path, target: Path) -> None:
    """Copy a Claude reference file without top-level YAML agent-like metadata."""
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


def _render_openstudio_modeler_agent(workspace_root: Path) -> str:
    """Render the Claude Code agent activated as the main thread by settings.json."""
    prompt_path = agent_source_for_host(workspace_root, "claude", "openstudio-modeler")
    prompt = prompt_path.read_text(encoding="utf-8")
    return (
        "---\n"
        "name: openstudio-modeler\n"
        "description: Senior OpenStudio modeler for MCP-backed model editing, "
        "simulation, results, SDK lookup, and long-running workflow state.\n"
        "model: sonnet\n"
        "effort: high\n"
        "---\n\n"
        f"{prompt.rstrip()}\n"
    )


def _render_learning_monitor_config() -> str:
    """Render a passive Claude monitor for runtime learning events."""
    return (
        json.dumps(
            [
                {
                    "name": "openstudio-learning-events",
                    "command": '"${CLAUDE_PLUGIN_ROOT}"/bin/openstudio-ai-learning-monitor',
                    "description": (
                        "Passive notifications for OpenStudio AI candidate learning events."
                    ),
                    "when": "on-skill-invoke:propose-measure",
                }
            ],
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
    )


def _learning_monitor_script() -> str:
    """Return a small monitor that tails learning_events.jsonl when present."""
    return '''#!/usr/bin/env python3
"""Emit OpenStudio AI learning events for Claude Code monitor notifications."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def candidate_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.getenv("OPENSTUDIO_AI_LEARNING_EVENT_LOG", "").strip()
    if explicit:
        paths.append(Path(explicit).expanduser())
    project_dir = os.getenv("CLAUDE_PROJECT_DIR", "").strip()
    if project_dir:
        paths.append(Path(project_dir) / "logs" / "learning_events.jsonl")
    data_dir = os.getenv("OPENSTUDIO_AI_DATA_DIR", "").strip()
    if data_dir:
        paths.append(Path(data_dir) / "logs" / "learning_events.jsonl")
    return paths


def first_existing_path() -> Path | None:
    for path in candidate_paths():
        if path.exists():
            return path
    return None


def main() -> int:
    path = first_existing_path()
    if path is None:
        return 0
    with path.open("r", encoding="utf-8") as stream:
        stream.seek(0, os.SEEK_END)
        while True:
            line = stream.readline()
            if line:
                print(line.rstrip(), flush=True)
            else:
                time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_plugin_readme(
    plan: HostLaunchPlan, workspace_root: Path, runtime_mode: str
) -> str:
    """Render the README shipped with the exported plugin."""
    skill_names = "\n".join(
        f"- `{skill}`" for skill in skill_ids_for_host(workspace_root, "claude")
    )
    return (
        "# OpenStudio AI\n\n"
        "OpenStudio AI is a Claude plugin package for building-energy modeling "
        "workflows using OpenStudio, MCP tools, reusable skills, and a reviewed "
        "SDK knowledge base.\n\n"
        "## What It Includes\n\n"
        "- `.mcp.json`: registers the `openstudio_ai` MCP server.\n"
        "- `agents/openstudio-modeler.md`: the OpenStudio modeler agent prompt.\n"
        "- `settings.json`: sets `agent` to `openstudio-modeler`, activating it "
        "as the main Claude Code thread while the plugin is enabled.\n"
        "- `skills/`: Claude-native workflow and model-editing skills.\n"
        "- `skills/*/references/`: reviewed SDK context packs, schemas, and workflow contracts.\n"
        "- `monitors/`: passive learning-event notifications for candidate learning workflows.\n"
        "- `bin/`: monitor helper executables.\n\n"
        "## User-Facing Skills\n\n"
        "- `/openstudio-ai:add-vav-reheat`: plan and execute a VAV reheat workflow.\n"
        "- `/openstudio-ai:simulate`: run or prepare an OpenStudio simulation workflow.\n"
        "- `/openstudio-ai:query-results`: retrieve SQL-backed simulation results.\n\n"
        "## Runtime Skills\n\n"
        f"{skill_names}\n\n"
        "## Runtime Note\n\n"
        f"Runtime mode: `{runtime_mode}`.\n\n"
        "In `local` mode, this plugin references a source checkout. In `installed` "
        "and `marketplace` mode, it expects the `openstudio-ai-mcp` command to be "
        "available on the user's machine.\n\n"
        "## Claude Code Activation\n\n"
        "Claude Code does not automatically read arbitrary plugin instruction "
        "files. This package uses the supported `settings.json` `agent` key to "
        "activate `agents/openstudio-modeler.md` as the main thread. If a host or "
        "managed policy ignores plugin settings, the skills and MCP server still "
        "load, but natural-language orchestration will depend on the user invoking "
        "the OpenStudio skills explicitly.\n"
    )


def _render_connectors_doc(workspace_root: Path, runtime_mode: str) -> str:
    """Render connector documentation for the plugin package."""
    if runtime_mode == "local":
        runtime_text = (
            "The current `.mcp.json` points to the local checkout:\n\n"
            f"- `{workspace_root}`\n\n"
        )
    else:
        runtime_text = (
            "The current `.mcp.json` points to the installed runtime command:\n\n"
            "- `openstudio-ai-mcp --transport stdio`\n\n"
        )
    return (
        "# OpenStudio AI Connectors\n\n"
        "This plugin uses one local MCP server.\n\n"
        "| Connector | Type | Purpose |\n"
        "| --- | --- | --- |\n"
        "| `openstudio_ai` | local stdio MCP | OpenStudio model lifecycle, simulation, "
        "results, approved measures, and SDK documentation lookup |\n\n"
        f"{runtime_text}"
        "OpenStudio and EnergyPlus availability depends on the local environment.\n"
    )


def _write_installer_assets(installers_dir: Path) -> None:
    """Write shared marketplace runtime helpers with Claude reload guidance."""
    write_runtime_helpers(
        installers_dir,
        post_install_guidance=(
            "If Claude Code already marked the MCP server as failed, run /reload-plugins "
            "or reconnect the failed MCP server so it starts openstudio-ai-mcp again."
        ),
    )


def _default_workspace_root() -> Path:
    """Return the OpenStudio AI example root from this adapter module."""
    return Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for project install and plugin export."""
    parser = argparse.ArgumentParser(
        description="Install the OpenStudio AI harness into Claude Code."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser(
        "install", help="Create or preview Claude Code project config."
    )
    install.add_argument(
        "--target-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory where .mcp.json and .claude/CLAUDE.md should be written.",
    )
    install.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_workspace_root(),
        help="OpenStudio AI harness root.",
    )
    install.add_argument(
        "--dry-run", action="store_true", help="Preview files without writing them."
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Append to an existing unmanaged CLAUDE.md.",
    )
    install.add_argument(
        "--runtime-mode",
        choices=sorted(RUNTIME_MODES),
        default="local",
        help="Runtime connection mode for generated MCP config.",
    )

    export = subparsers.add_parser(
        "export-plugin", help="Export a Claude plugin-style package."
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
    """CLI entrypoint for Claude Code adapter operations."""
    args = _parse_args()
    if args.command == "install":
        adapter = ClaudeCodeAdapter(
            config=HostAdapterConfig(
                host_name="claude_code",
                workspace_root=args.workspace_root,
                runtime_mode=args.runtime_mode,
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
        adapter = ClaudeCodeAdapter(
            config=HostAdapterConfig(
                host_name="claude_code",
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
        print(f"{mode} marketplace: {result.marketplace_dir}")
        print(f"{mode} plugin: {result.plugin_dir}")
        for path in result.files:
            print(f"- {path}")
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
