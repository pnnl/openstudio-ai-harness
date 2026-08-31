# OpenStudio AI standalone development environment

This Python 3.12+ subproject runs the AUTOMA-AI agent and Streamlit UI. It is
not distributed in the `openstudio-ai` production wheel or source archive.

From the repository root:

```bash
uv sync --project standalone
uv run --project standalone python standalone/agent.py
uv run --project standalone streamlit run standalone/ui.py
uv run --project standalone python -m pytest -q standalone/tests
```
