from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RUNTIME_MODES = {"local", "installed", "marketplace"}


@dataclass(frozen=True)
class HarnessPaths:
    root: Path
    prompts_dir: Path
    skills_dir: Path
    mcp_dir: Path
    knowledge_dir: Path
    state_dir: Path


@dataclass(frozen=True)
class HostAdapterConfig:
    host_name: str
    workspace_root: Path
    runtime_mode: str = "local"
    enable_learning_capture: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.runtime_mode not in RUNTIME_MODES:
            raise ValueError(
                f"runtime_mode must be one of {sorted(RUNTIME_MODES)}, got {self.runtime_mode!r}"
            )


@dataclass(frozen=True)
class HostLaunchPlan:
    host_name: str
    system_prompt_files: list[Path]
    skill_paths: list[Path]
    mcp_entrypoint: Path
    blackboard_schema: Path
    learning_event_log: Path
    notes: list[str] = field(default_factory=list)
