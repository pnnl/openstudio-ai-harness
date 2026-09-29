import pytest

import standalone.ui as ui
from standalone.ui import (
    ChatbotRuntime,
    _artifact_contains_json_fence,
    _artifact_contains_python_fence,
    _format_status_text_for_display,
    _normalize_agent_stream_event,
    _parse_stream_chunk,
    _should_defer_artifact_render,
    _should_suppress_status_text,
    _split_python_fenced_blocks,
)


class _FakeMcpManager:
    def __init__(self, *, started: dict[str, bool] | None = None) -> None:
        self.started = started or {"openstudio_ai_mcp": True}
        self.configs = []
        self.stopped = False

    def add_server(self, config) -> bool:
        self.configs.append(config)
        return True

    async def start_all(self) -> dict[str, bool]:
        return self.started

    async def stop_all(self) -> dict[str, bool]:
        self.stopped = True
        return {name: True for name in self.started}


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.closed = False

    async def stream(self, prompt: str, session_id: str, task_id: str):
        self.calls.append((prompt, session_id, task_id))
        yield {"response_type": "text", "content": prompt}

    async def aclose(self) -> None:
        self.closed = True


def test_chatbot_runtime_streams_and_closes_local_resources(monkeypatch) -> None:
    manager = _FakeMcpManager()
    agent = _FakeAgent()
    monkeypatch.setattr(ui, "MCPServerManager", lambda: manager)
    monkeypatch.setattr(ui, "build_openstudio_ai_mcp_config", lambda: object())
    monkeypatch.setattr(ui, "build_openstudio_agent", lambda: agent)

    runtime = ChatbotRuntime()
    events = list(runtime.stream("hello", "browser-session"))
    runtime.close()

    assert events[0]["content"] == "hello"
    assert agent.calls[0][:2] == ("hello", "browser-session")
    assert agent.closed is True
    assert manager.stopped is True
    assert not runtime._thread.is_alive()


def test_chatbot_runtime_cleans_up_partial_mcp_startup(monkeypatch) -> None:
    manager = _FakeMcpManager(started={"openstudio_ai_mcp": False})
    monkeypatch.setattr(ui, "MCPServerManager", lambda: manager)
    monkeypatch.setattr(ui, "build_openstudio_ai_mcp_config", lambda: object())

    with pytest.raises(RuntimeError, match="failed to start"):
        ChatbotRuntime()

    assert manager.stopped is True


def test_openstudio_ui_preserves_structured_final_data_artifacts() -> None:
    event = _normalize_agent_stream_event(
        {
            "response_type": "data",
            "is_task_complete": True,
            "content": {"skill_count": 5},
            "additional_artifacts": [
                {"response_type": "text", "content": "Five skills are available."}
            ],
        }
    )

    assert event == {
        "response_type": "data",
        "content": {"skill_count": 5},
        "is_task_complete": True,
        "additional_artifacts": [
            {"response_type": "text", "content": "Five skills are available."}
        ],
    }


def test_openstudio_ui_parses_status_update_separately() -> None:
    event = _parse_stream_chunk(
        {
            "result": {
                "kind": "status-update",
                "contextId": "ctx-1",
                "status": {
                    "state": "working",
                    "message": {
                        "parts": [
                            {
                                "kind": "text",
                                "text": "Inspecting model geometry.",
                            }
                        ]
                    },
                },
            }
        }
    )

    assert event == {
        "kind": "status-update",
        "context_id": "ctx-1",
        "state": "working",
        "text": "Inspecting model geometry.",
        "data": [],
    }


def test_openstudio_ui_parses_artifact_update_separately() -> None:
    event = _parse_stream_chunk(
        {
            "result": {
                "kind": "artifact-update",
                "contextId": "ctx-1",
                "artifact": {
                    "parts": [
                        {
                            "kind": "text",
                            "text": "Final model edit summary.",
                        }
                    ]
                },
            }
        }
    )

    assert event == {
        "kind": "artifact-update",
        "context_id": "ctx-1",
        "state": None,
        "text": "Final model edit summary.",
        "data": [],
    }


def test_openstudio_ui_parses_data_artifact_update() -> None:
    event = _parse_stream_chunk(
        {
            "result": {
                "kind": "artifact-update",
                "contextId": "ctx-1",
                "artifact": {
                    "parts": [
                        {
                            "kind": "data",
                            "data": {"ok": True, "counts": {"spaces": 6}},
                        }
                    ]
                },
            }
        }
    )

    assert event["kind"] == "artifact-update"
    assert event["context_id"] == "ctx-1"
    assert event["text"] is None
    assert event["data"] == [{"ok": True, "counts": {"spaces": 6}}]


def test_openstudio_ui_parses_mixed_text_and_data_artifact_update() -> None:
    event = _parse_stream_chunk(
        {
            "result": {
                "kind": "artifact-update",
                "contextId": "ctx-1",
                "artifact": {
                    "parts": [
                        {"kind": "text", "text": "Final summary."},
                        {"kind": "data", "data": {"ok": True}},
                    ]
                },
            }
        }
    )

    assert event["text"] == "Final summary."
    assert event["data"] == [{"ok": True}]


def test_openstudio_ui_suppresses_successful_load_skill_status() -> None:
    assert _should_suppress_status_text(
        "\n\n **Tool load_skill responded**: SKILL: sdk_geometry\n\n"
    )


def test_openstudio_ui_suppresses_load_skill_status_by_prefix() -> None:
    assert _should_suppress_status_text("Tool load_skill responded: ")


def test_openstudio_ui_suppresses_openstudio_skill_response() -> None:
    assert _should_suppress_status_text(
        "Tool load_skill responded: SKILL: openstudio_sdk_model_editor\n"
        "SOURCE: /tmp/openstudio-ai-harness/"
        "skills/openstudio_sdk_model_editor.md\n\nScope\n\nUse this skill only..."
    )


def test_openstudio_ui_keeps_load_skill_error_status() -> None:
    assert not _should_suppress_status_text(
        "\n\n **Tool load_skill responded**: Error: missing skill\n\n"
    )


def test_openstudio_ui_normalizes_streamed_status_whitespace() -> None:
    assert (
        _format_status_text_for_display(" For example:\n   - **Building")
        == "For example:\n- **Building"
    )


def test_openstudio_ui_limits_excess_status_blank_lines() -> None:
    assert (
        _format_status_text_for_display("First\n\n\n\n   Second")
        == "First\nSecond"
    )


def test_openstudio_ui_removes_blank_lines_before_status_options() -> None:
    assert (
        _format_status_text_for_display(
            "What aspects are you most interested in? For example:\n\n\n\n"
            "Geometry & envelope: number of stories"
        )
        == "What aspects are you most interested in? For example:\n"
        "Geometry & envelope: number of stories"
    )


def test_openstudio_ui_defers_incomplete_markdown_table_rows() -> None:
    assert _should_defer_artifact_render("📐 Geometry\n|")
    assert _should_defer_artifact_render("📐 Geometry\n| Item | Count")
    assert not _should_defer_artifact_render("📐 Geometry\n| Item | Count |\n")
    assert not _should_defer_artifact_render("Plain text without a table")


def test_openstudio_ui_detects_python_script_artifacts() -> None:
    assert _artifact_contains_python_fence("Run this:\n```python\nprint('x')\n```")
    assert _artifact_contains_python_fence("Run this:\n```PYTHON\nprint('x')\n```")
    assert not _artifact_contains_python_fence("```json\n{\"ok\": true}\n```")


def test_openstudio_ui_splits_python_script_from_surrounding_text() -> None:
    assert _split_python_fenced_blocks(
        "Intro\n```python\nprint('x')\n```\nOutro"
    ) == [
        ("text", "Intro\n"),
        ("python", "```python\nprint('x')\n```"),
        ("text", "\nOutro"),
    ]


def test_openstudio_ui_detects_json_data_artifacts() -> None:
    assert _artifact_contains_json_fence("```json\n{\"ok\": true}\n```")
    assert _artifact_contains_json_fence("```JSON\n{\"ok\": true}\n```")
    assert not _artifact_contains_json_fence("```python\nprint('x')\n```")
