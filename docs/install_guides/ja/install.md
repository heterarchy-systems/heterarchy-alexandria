# heterarchy-alexandria install

> Maintenance status: this Japanese page is currently an unmaintained placeholder. Use `../en/install.md` or `../ko/install.md` for the maintained install flow until a real translation is added.

The frontend runtime has been removed. Install the backend/CLI/MCP service and connect it to an Obsidian Markdown vault.

## Generated vault

```bash
cd backend
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000
```

In another terminal after the backend starts:

```bash
cd backend
curl -fsS -X POST http://127.0.0.1:8000/obsidian/init
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild
```

Open `~/.hermes/heterarchy-alexandria/data/obsidian-vault` in Obsidian.

## Existing `Alexandria` vault

```bash
cd backend
export SERVICE_OBSIDIAN_VAULT_PATH="$HOME/Desktop/Alexandria"
export SERVICE_ALEXANDRIA_OBSIDIAN_ROOT="."
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Root `.` means the vault itself is the Alexandria workspace and prevents an `Alexandria/Alexandria` nested layout.

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
