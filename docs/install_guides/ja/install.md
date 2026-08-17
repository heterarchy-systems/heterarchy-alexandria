# heterarchy-alexandria install

> Maintenance status: this Japanese page is currently an unmaintained placeholder. Use `../en/install.md` or `../ko/install.md` for the maintained install flow until a real translation is added.

The frontend runtime has been removed. Install the backend/CLI/MCP service and connect it to an Obsidian Markdown vault.

## Generated vault

```bash
cd backend
uv sync
uv run heterarchy-alexandria setup --mode backend-daemon --apply --write-guidebook --run-migrations
uv run heterarchy-alexandria serve \
  --env-file "$HOME/.hermes/heterarchy-alexandria/.env" \
  --host 127.0.0.1 \
  --port 8000
```

In another terminal after the backend starts:

```bash
cd backend
uv run heterarchy-alexandria obsidian init
uv run heterarchy-alexandria obsidian reindex
```

Open `~/.hermes/heterarchy-alexandria/data/obsidian-vault` in Obsidian.

## Existing `Alexandria` vault

```bash
cd backend
uv sync
uv run heterarchy-alexandria setup \
  --mode backend-daemon \
  --apply \
  --write-guidebook \
  --run-migrations \
  --obsidian-vault-path "$HOME/Desktop/Alexandria" \
  --alexandria-obsidian-root "."
```

Root `.` means the vault itself is the Alexandria workspace and prevents an `Alexandria/Alexandria` nested layout.

Then start the backend with the generated env file:

```bash
uv run heterarchy-alexandria serve \
  --env-file "$HOME/.hermes/heterarchy-alexandria/.env" \
  --host 127.0.0.1 \
  --port 8000
```

## Obsidian side pane

```bash
brew install --cask obsidian
cd backend
uv run heterarchy-alexandria obsidian install-local \
  --vault-path "$HOME/Desktop/Alexandria" \
  --plugin-install-mode copy
```

Enable **Alexandria Librarian** in Obsidian Community plugins while the backend is running.

## Docker Compose

```bash
docker compose up --build
```
