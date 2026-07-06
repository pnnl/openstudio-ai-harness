from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from adapters.base import OpenStudioAiHostAdapter
from adapters.contracts import RUNTIME_MODES, HostAdapterConfig, HostLaunchPlan
from harness.registry import discover_harness_assets

DEFAULT_PLUGIN_NAME = "openstudio-ai"
MARKETPLACE_NAME = "openstudio-ai-local"
SERVER_NAME = "openstudio_ai"


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
            skill_paths=assets.skill_files,
            mcp_entrypoint=assets.mcp_entrypoint,
            blackboard_schema=assets.blackboard_schema,
            learning_event_log=assets.learning_event_log,
            notes=[
                "Export skills, MCP config, knowledge, and instructions as a Codex plugin."
            ],
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
        plugin_dir / ".mcp.json",
        plugin_dir / "README.md",
        plugin_dir / "CONNECTORS.md",
        plugin_dir / "blackboard" / "schemas" / plan.blackboard_schema.name,
        plugin_dir / "learning" / "README.md",
        plugin_dir / "learning" / "candidates" / ".gitkeep",
    ]
    if runtime_mode == "marketplace":
        files.extend(
            [
                plugin_dir / "commands" / "setup-openstudio-ai.md",
                plugin_dir / "commands" / "doctor-openstudio-ai.md",
                plugin_dir / "commands" / "repair-openstudio-ai.md",
                plugin_dir / "installers" / "install_runtime.py",
                plugin_dir / "installers" / "doctor_runtime.py",
            ]
        )
    files.extend(
        plugin_dir / "instructions" / path.name for path in plan.system_prompt_files
    )
    files.extend(
        plugin_dir / "skills" / _skill_dir_name(path) / "SKILL.md"
        for path in plan.skill_paths
    )
    files.extend(
        plugin_dir / "learning" / "schemas" / path.name
        for path in sorted(
            (workspace_root / "learning" / "harness_pipeline" / "schemas").glob(
                "*.json"
            )
        )
    )

    knowledge_root = workspace_root / "knowledge"
    if knowledge_root.exists():
        files.extend(
            plugin_dir / "knowledge" / path.relative_to(knowledge_root)
            for path in knowledge_root.rglob("*")
            if path.is_file()
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
    (plugin_dir / "commands").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "installers").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "skills").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "instructions").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "blackboard" / "schemas").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "learning" / "schemas").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "learning" / "candidates").mkdir(parents=True, exist_ok=True)

    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        _render_plugin_json(),
        encoding="utf-8",
    )
    (plugin_dir / ".mcp.json").write_text(
        _render_mcp_config(workspace_root, runtime_mode), encoding="utf-8"
    )
    (plugin_dir / "README.md").write_text(
        _render_plugin_readme(plan, runtime_mode), encoding="utf-8"
    )
    (plugin_dir / "CONNECTORS.md").write_text(
        _render_connectors_doc(workspace_root, runtime_mode), encoding="utf-8"
    )

    for command_name, content in _command_docs(runtime_mode).items():
        (plugin_dir / "commands" / command_name).write_text(content, encoding="utf-8")

    if runtime_mode == "marketplace":
        _write_installer_assets(plugin_dir / "installers")

    for prompt in plan.system_prompt_files:
        shutil.copy2(prompt, plugin_dir / "instructions" / prompt.name)

    for skill in plan.skill_paths:
        target_dir = plugin_dir / "skills" / _skill_dir_name(skill)
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill, target_dir / "SKILL.md")

    shutil.copy2(
        plan.blackboard_schema,
        plugin_dir / "blackboard" / "schemas" / plan.blackboard_schema.name,
    )
    shutil.copy2(
        workspace_root / "learning" / "harness_pipeline" / "runtime_learning.md",
        plugin_dir / "learning" / "README.md",
    )
    (plugin_dir / "learning" / "candidates" / ".gitkeep").write_text(
        "", encoding="utf-8"
    )
    for schema in sorted(
        (workspace_root / "learning" / "harness_pipeline" / "schemas").glob("*.json")
    ):
        shutil.copy2(schema, plugin_dir / "learning" / "schemas" / schema.name)

    knowledge_root = workspace_root / "knowledge"
    if knowledge_root.exists():
        shutil.copytree(knowledge_root, plugin_dir / "knowledge")


def _render_plugin_json() -> str:
    """Render Codex `.codex-plugin/plugin.json` with validation-required metadata."""
    return (
        json.dumps(
            {
                "name": DEFAULT_PLUGIN_NAME,
                "version": "0.1.0",
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
                "openstudio_mcp.server",
                "--transport",
                "stdio",
                "--workspace-root",
                str(workspace_root / ".openstudio_mcp_workspace"),
            ],
            "env": {
                "PYTHONPATH": str(workspace_root),
                "OPENSTUDIO_AI_ROOT": str(workspace_root),
            },
        }
    if runtime_mode in {"installed", "marketplace"}:
        return {
            "command": "openstudio-ai-mcp",
            "args": ["--transport", "stdio"],
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
        "## Runtime Setup\n\n"
        "After installation, ask Codex to run `setup-openstudio-ai`. The setup command "
        "checks Python, checks `openstudio-ai-mcp`, and explains any missing installation "
        "steps in energy-modeler language.\n"
    )


def _render_plugin_readme(plan: HostLaunchPlan, runtime_mode: str) -> str:
    """Render the README shipped with the Codex plugin."""
    skill_names = "\n".join(f"- `{_skill_dir_name(path)}`" for path in plan.skill_paths)
    return (
        "# OpenStudio AI\n\n"
        "OpenStudio AI is a Codex plugin package for building-energy modeling workflows "
        "using OpenStudio, MCP tools, reusable skills, and reviewed knowledge.\n\n"
        "## What It Includes\n\n"
        "- `.mcp.json`: registers the `openstudio_ai` MCP server.\n"
        "- `skills/`: separate runtime skills for model editing and HVAC workflows.\n"
        "- `knowledge/`: reviewed OpenStudio SDK recipes and context packs.\n"
        "- `instructions/`: harness, blackboard, learning, and promotion contracts.\n"
        "- `blackboard/schemas/`: workflow-state schema for long-running tasks.\n\n"
        "## Skills\n\n"
        f"{skill_names}\n\n"
        "## Runtime Note\n\n"
        f"Runtime mode: `{runtime_mode}`.\n\n"
        "In `local` mode, this plugin references a source checkout. In `installed` "
        "and `marketplace` mode, it expects the `openstudio-ai-mcp` command to be "
        "available on the user's machine.\n"
    )


def _render_connectors_doc(workspace_root: Path, runtime_mode: str) -> str:
    """Render connector documentation for the Codex plugin package."""
    if runtime_mode == "local":
        runtime_text = (
            "The current `.mcp.json` points to the local checkout:\n\n"
            f"- `{workspace_root}`\n"
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


def _command_docs(runtime_mode: str) -> dict[str, str]:
    """Return command files for common OpenStudio workflows and setup."""
    commands = {
        "add-vav-reheat.md": _command_markdown(
            name="add-vav-reheat",
            description="Plan and execute a phased OpenStudio VAV reheat workflow.",
            body=(
                "# Add VAV Reheat\n\n"
                "Use the OpenStudio AI VAV reheat parent workflow skill. Maintain "
                "workflow state through the blackboard contract, load only the child "
                "skill needed for the current phase, and use MCP tools for deterministic "
                "model lifecycle operations when appropriate.\n"
            ),
        ),
        "simulate.md": _command_markdown(
            name="simulate",
            description="Run, poll, and collect artifacts from an OpenStudio simulation.",
            body=(
                "# Simulate\n\n"
                "Use the `openstudio_ai` MCP simulation tools to run, poll, and collect "
                "artifacts from OpenStudio simulations. Do not run simulations through "
                "ad hoc shell commands when MCP tools are available.\n"
            ),
        ),
        "query-results.md": _command_markdown(
            name="query-results",
            description="Query SQL-backed OpenStudio simulation results through MCP tools.",
            body=(
                "# Query Results\n\n"
                "Use the `openstudio_ai` MCP result tools for SQL-backed annual, design-day, "
                "and summary result retrieval. Attribute assumptions and missing outputs "
                "in the final answer.\n"
            ),
        ),
        "propose-measure.md": _command_markdown(
            name="propose-measure",
            description="Draft a candidate OpenStudio measure from a repeated script or workflow.",
            body=(
                "# Propose Measure\n\n"
                "Summarize the repeated OpenStudio script or workflow as a candidate measure. "
                "Write candidate JSON to `learning/candidates/` using "
                "`learning/schemas/candidate_measure.schema.json`. Do not edit trusted "
                "`knowledge/`, `skills/`, or approved measures directly. State that review "
                "and eval validation are required before promotion.\n"
            ),
        ),
    }
    if runtime_mode == "marketplace":
        commands.update(_marketplace_command_docs())
    return commands


def _marketplace_command_docs() -> dict[str, str]:
    """Return marketplace setup commands for no-code runtime onboarding."""
    return {
        "setup-openstudio-ai.md": _command_markdown(
            name="setup-openstudio-ai",
            description="Check and prepare the OpenStudio AI runtime for energy modeling.",
            body=(
                "# Setup OpenStudio AI\n\n"
                "Help the user get OpenStudio AI ready without assuming programming experience.\n\n"
                "1. Explain that OpenStudio AI needs a local runtime command named "
                "`openstudio-ai-mcp` so the AI assistant can safely run OpenStudio tools.\n"
                "2. Check whether Python is available using `python --version`. If that fails, "
                "try `python3 --version`.\n"
                "3. Check whether `openstudio-ai-mcp` is available by running "
                "`openstudio-ai-mcp --help`.\n"
                "4. Run `python installers/doctor_runtime.py`. If `python` is unavailable, "
                "try `python3 installers/doctor_runtime.py`.\n"
                "5. If the runtime is missing, explain the issue in normal energy-modeler "
                "language and ask before running `python installers/install_runtime.py`.\n"
                "6. When `openstudio-ai` is available, run `openstudio-ai doctor`.\n"
                "7. Summarize readiness for model loading, HVAC workflow support, simulation, "
                "results, SDK lookup, and workflow state tracking.\n"
            ),
        ),
        "doctor-openstudio-ai.md": _command_markdown(
            name="doctor-openstudio-ai",
            description="Diagnose OpenStudio AI runtime readiness.",
            body=(
                "# Doctor OpenStudio AI\n\n"
                "Run `python installers/doctor_runtime.py`, then run `openstudio-ai doctor` "
                "if the command exists. Explain missing Python, missing runtime, missing "
                "OpenStudio, or path problems as setup items, not programming failures.\n"
            ),
        ),
        "repair-openstudio-ai.md": _command_markdown(
            name="repair-openstudio-ai",
            description="Guide non-destructive repair of the OpenStudio AI runtime.",
            body=(
                "# Repair OpenStudio AI\n\n"
                "First run the doctor command. If the runtime is missing, ask for approval "
                "before running `python installers/install_runtime.py`. Do not delete user "
                "models, simulation outputs, or project files. Describe each repair step in "
                "plain language for an energy modeler.\n"
            ),
        ),
    }


def _command_markdown(*, name: str, description: str, body: str) -> str:
    """Render a Codex command file with YAML frontmatter."""
    return "---\n" f"name: {name}\n" f"description: {description}\n" "---\n\n" f"{body}"


def _write_installer_assets(installers_dir: Path) -> None:
    """Write cross-platform runtime installer and doctor helper scripts."""
    installers_dir.mkdir(parents=True, exist_ok=True)
    (installers_dir / "doctor_runtime.py").write_text(
        _doctor_runtime_script(), encoding="utf-8"
    )
    (installers_dir / "install_runtime.py").write_text(
        _install_runtime_script(), encoding="utf-8"
    )


def _doctor_runtime_script() -> str:
    """Return the runtime doctor helper script shipped in marketplace exports."""
    return '''"""Check whether the OpenStudio AI runtime can be used by this plugin."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys


def command_status(command: str) -> dict[str, object]:
    path = shutil.which(command)
    return {"command": command, "available": path is not None, "path": path}


def main() -> int:
    report = {
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "openstudio_ai_mcp": command_status("openstudio-ai-mcp"),
        "openstudio_ai": command_status("openstudio-ai"),
    }
    print(json.dumps(report, indent=2))

    if not report["openstudio_ai_mcp"]["available"]:
        print(
            "\\nOpenStudio AI runtime is not installed yet. "
            "Ask the user before running install_runtime.py."
        )
        return 2

    result = subprocess.run(
        ["openstudio-ai-mcp", "--help"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        print("\\nFound openstudio-ai-mcp, but it did not start cleanly.")
        print(result.stderr.strip())
        return result.returncode

    print("\\nOpenStudio AI MCP runtime command is available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _install_runtime_script() -> str:
    """Return the runtime installer script shipped in marketplace exports."""
    return '''"""Install or repair the OpenStudio AI runtime package for this plugin."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


DEFAULT_PACKAGE_SPEC = "openstudio-ai"


def run(command: list[str]) -> int:
    print(f"\\n$ {' '.join(command)}")
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> int:
    print("OpenStudio AI runtime installer")
    print("===============================")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version.split()[0]}")

    package_spec = os.getenv("OPENSTUDIO_AI_PACKAGE_SPEC", DEFAULT_PACKAGE_SPEC)
    if shutil.which("openstudio-ai") and shutil.which("openstudio-ai-mcp"):
        print("\\nOpenStudio AI commands are already available. Initializing runtime storage.")
    else:
        print(f"\\nInstalling runtime package: {package_spec}")
        print(
            "Set OPENSTUDIO_AI_PACKAGE_SPEC to a wheel path, internal index spec, "
            "or pinned version if your organization does not install from PyPI."
        )
        code = run([sys.executable, "-m", "pip", "install", "--upgrade", package_spec])
        if code != 0:
            print(
                "\\nRuntime package installation failed. Check Python permissions, "
                "network access, package index access, or ask your support contact "
                "for an approved OpenStudio AI package."
            )
            return code

    # Do not call the `openstudio-ai` console script here: after pip installs
    # the package, Python's scripts directory may not be visible on PATH in this
    # shell yet. The top-level `cli` module is importable in the current Python
    # environment immediately after installation, so it is the stable bootstrap
    # path for first-run storage initialization.
    code = run([sys.executable, "-m", "cli", "install-runtime"])
    if code != 0:
        print("\\nInstalled package, but runtime initialization failed.")
        return code

    if not shutil.which("openstudio-ai-mcp"):
        print(
            "\\nThe package installed, but openstudio-ai-mcp is not on PATH in this shell. "
            "Restart the AI tool or add Python's scripts directory to PATH, then rerun doctor."
        )
        return 3

    print("\\nOpenStudio AI runtime installation completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _skill_dir_name(path: Path) -> str:
    """Convert repo skill filenames into plugin skill folder names."""
    return path.stem.replace("_", "-")


def _default_workspace_root() -> Path:
    """Return the OpenStudio AI example root from this adapter module."""
    return Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for Codex plugin export."""
    parser = argparse.ArgumentParser(
        description="Export the OpenStudio AI harness as a Codex plugin."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
