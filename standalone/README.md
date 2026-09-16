# OpenStudio AI standalone development environment

This Python 3.10+ subproject runs the AUTOMA-AI agent inside the Streamlit UI.
It is not distributed in the `openstudio-ai` production wheel or source archive.

From the repository root:

```bash
cp sample.env .env
uv sync --project standalone
uv run --project standalone streamlit run standalone/ui.py --server.port 8504
uv run --project standalone python -m pytest -q standalone/tests
```

Opening the UI builds the local agent and starts the local OpenStudio MCP
process it uses; no A2A agent server or agent card is required. The agent and
UI share the repository-root `.env` and write/read telemetry at
`logs/telemetry.jsonl`.

## Docker Compose demo

From the repository root, create `.env` with the model credential required by
the agent, then start the self-contained UI:

```bash
cp sample.env .env  # only when .env does not already exist
docker compose --profile standalone up --build standalone
```

Open [http://localhost:8504](http://localhost:8504). To choose a different host port,
use, for example:

```bash
STREAMLIT_HOST_PORT=8505 docker compose --profile standalone up --build standalone
```

The MCP process is started inside the container by the UI and is not published
to the host.

## Devcontainer demo

The repository devcontainer is Compose-backed and publishes port 8504 from
Docker Desktop. After **Dev Containers: Rebuild Container**, the UI starts
automatically and is available at [http://localhost:8504](http://localhost:8504).
If startup needs inspection, use:

```bash
tail -f logs/streamlit.log
```
