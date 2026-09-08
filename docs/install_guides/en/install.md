# Install heterarchy-alexandria

The frontend runtime has been removed. Install the backend/CLI/MCP service and connect it to Obsidian Markdown.

## Generated vault

Terminal 1:

```bash
cd backend
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000
```

Terminal 2:

```bash
cd backend
curl -fsS -X POST http://127.0.0.1:8000/obsidian/init
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild
```

Open `~/.hermes/heterarchy-alexandria/data/obsidian-vault` in Obsidian.

## Existing vault named Alexandria

```bash
cd backend
export SERVICE_OBSIDIAN_VAULT_PATH="$HOME/Desktop/Alexandria"
export SERVICE_ALEXANDRIA_OBSIDIAN_ROOT="."
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use root `.` when the vault itself is the Alexandria workspace; this avoids `Alexandria/Alexandria` nesting.

## Verify the backend and MCP surface

```bash
brew install --cask obsidian
curl -fsS http://127.0.0.1:8000/operations/readiness | jq
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild | jq
```

## Docker Compose

```bash
docker compose up --build
```

The backend is available at `http://127.0.0.1:8000`.
