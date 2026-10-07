"""Drive the exported setup skill with a real model inside a runtime environment.

The model plays the host agent (Claude Code / Codex): it receives the exported
``setup-openstudio-ai`` SKILL.md and a shell tool that runs inside the
container. The user is simulated: every approval request is granted and logged
so tests can check that the skill's approval gates were honored.

Configuration comes from a ``.env`` file (tests/runtime_envs/.env, then the
repository root .env) or the environment; see ``.env.example``:

    LLM_API_KEY=...                                   # required
    LLM_BASE_URL=https://ai-incubator-api.pnnl.gov    # any OpenAI-compatible endpoint
    LLM_MODEL=claude-sonnet-5-5-project
    LLM_TEMPERATURE=             # optional; Claude models on the Depot reject 0

Requires ``openai`` (``uv run --extra dev --with openai==2.6.1 pytest ...``).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime_env_harness import EXPORT_ROOT, REPO_ROOT, RuntimeEnv

DEFAULT_BASE_URL = "https://ai-incubator-api.pnnl.gov"
DEFAULT_MODEL = "claude-sonnet-5-5-project"
MAX_TURNS = int(os.getenv("LLM_AGENT_MAX_TURNS", "30"))
OUTPUT_LIMIT = 6000
COMMAND_TIMEOUT_S = 900

SKILL_PATH = "claude/openstudio-ai/skills/setup-openstudio-ai/SKILL.md"


def load_llm_settings() -> dict[str, str] | None:
    """Return model settings, or None when no API key is configured."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv is a runtime dependency; stay tolerant.
        load_dotenv = None
    if load_dotenv is not None:
        load_dotenv(Path(__file__).with_name(".env"), override=False)
        load_dotenv(REPO_ROOT / ".env", override=False)
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "base_url": os.getenv("LLM_BASE_URL", "").strip() or DEFAULT_BASE_URL,
        "model": os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL,
        "temperature": os.getenv("LLM_TEMPERATURE", "").strip(),
    }


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Run a command with /bin/sh in the user's terminal on their machine and "
                "return the exit code, stdout, and stderr. Long downloads are allowed."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user a question, such as approval before an action the "
                "instructions say needs approval. Returns the user's answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "End setup and give the user the final readiness summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "core_ready": {
                        "type": "boolean",
                        "description": "True only if the doctor reported core_ready: true.",
                    },
                    "plugin_ready": {"type": "boolean"},
                },
                "required": ["summary", "core_ready", "plugin_ready"],
            },
        },
    },
]

SYSTEM_PROMPT = """\
You are the AI host agent for an energy modeler who just installed the
OpenStudio AI marketplace plugin. The user asked you to run its setup skill.

Follow the skill instructions below exactly. You act only through tools:
- run_shell runs commands in the user's terminal on their machine.
- ask_user asks the user; use it for every approval the skill requires.
- finish ends setup with your readiness summary.

You cannot reload or restart the host application yourself; when the skill says
to reload, tell the user in your summary. Do not edit plugin files. The plugin
files are at {plugin_dir} (read-only).

<skill name="setup-openstudio-ai">
{skill}
</skill>
"""


@dataclass
class AgentTranscript:
    model: str
    commands: list[dict[str, Any]] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)
    final: dict[str, Any] | None = None
    turns: int = 0
    seconds: float = 0.0

    def command_index(self, needle: str) -> int | None:
        for index, item in enumerate(self.commands):
            if needle in item["command"]:
                return index
        return None

    def first_event(self, kind: str, needle: str) -> int | None:
        for index, (event_kind, text) in enumerate(self.events):
            if event_kind == kind and needle in text:
                return index
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "turns": self.turns,
            "seconds": round(self.seconds, 1),
            "questions": self.questions,
            "commands": [
                {k: item[k] for k in ("command", "exit_code", "seconds")}
                for item in self.commands
            ],
            "final": self.final,
        }


def run_setup_agent(
    env: RuntimeEnv,
    settings: dict[str, str],
    *,
    user_request: str = "Please set up OpenStudio AI on my machine.",
    shell_env: dict[str, str] | None = None,
) -> AgentTranscript:
    import openai

    client = openai.OpenAI(api_key=settings["api_key"], base_url=settings["base_url"])
    skill = env.read_text(f"{EXPORT_ROOT}/release-sim/{SKILL_PATH}")
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                skill=skill,
                plugin_dir=f"{EXPORT_ROOT}/release-sim/claude/openstudio-ai",
            ),
        },
        {"role": "user", "content": user_request},
    ]
    transcript = AgentTranscript(model=settings["model"])
    started = time.monotonic()

    sampling = (
        {"temperature": float(settings["temperature"])}
        if settings.get("temperature")
        else {}
    )
    for _ in range(MAX_TURNS):
        transcript.turns += 1
        response = client.chat.completions.create(
            model=settings["model"],
            messages=messages,
            tools=TOOLS,
            **sampling,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))
        if not message.tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "Continue, and call finish when setup is done.",
                }
            )
            continue
        for call in message.tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            output = _dispatch(
                env, transcript, call.function.name, arguments, shell_env
            )
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": output}
            )
            if transcript.final is not None:
                transcript.seconds = time.monotonic() - started
                return transcript

    transcript.seconds = time.monotonic() - started
    return transcript


def _dispatch(
    env: RuntimeEnv,
    transcript: AgentTranscript,
    name: str,
    arguments: dict[str, Any],
    shell_env: dict[str, str] | None,
) -> str:
    if name == "run_shell":
        command = str(arguments.get("command", ""))
        result = env.exec(
            ["sh", "-c", command], env=shell_env, timeout=COMMAND_TIMEOUT_S
        )
        transcript.commands.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "seconds": round(result.seconds, 1),
            }
        )
        transcript.events.append(("command", command))
        return json.dumps(
            {
                "exit_code": result.returncode,
                "stdout": result.stdout[-OUTPUT_LIMIT:],
                "stderr": result.stderr[-OUTPUT_LIMIT:],
            }
        )
    if name == "ask_user":
        question = str(arguments.get("question", ""))
        transcript.questions.append(question)
        transcript.events.append(("question", question))
        return "Yes, approved. Go ahead."
    if name == "finish":
        transcript.final = {
            "summary": str(arguments.get("summary", "")),
            "core_ready": bool(arguments.get("core_ready")),
            "plugin_ready": bool(arguments.get("plugin_ready")),
        }
        return "Setup ended."
    return f"Unknown tool: {name}"
