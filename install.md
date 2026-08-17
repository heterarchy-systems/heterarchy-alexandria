# Install

heterarchy-alexandria installs as a backend/CLI/MCP service. The old frontend runtime has been removed.

## Requirements

- Python 3.13 through `uv`
- macOS Homebrew Cask only if you want Codex to install Obsidian locally
- Obsidian for the human-facing Markdown vault

## Backend daemon with generated vault

Terminal 1:

```bash
cd backend
uv sync
uv run heterarchy-alexandria setup --mode backend-daemon --apply --write-guidebook --run-migrations
uv run heterarchy-alexandria serve \
  --env-file "$HOME/.hermes/heterarchy-alexandria/.env" \
  --host 127.0.0.1 \
  --port 8000
```

Terminal 2:

```bash
cd backend
uv run heterarchy-alexandria obsidian init
uv run heterarchy-alexandria obsidian reindex
```

Open this vault in Obsidian:

```text
~/.hermes/heterarchy-alexandria/data/obsidian-vault
```

## Backend daemon with an existing Obsidian vault

Use this when you already created `~/Desktop/Alexandria` in Obsidian:

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

`--alexandria-obsidian-root "."` means Alexandria-managed notes live at the vault root, so setup does not create `Alexandria/Alexandria`.

Then start the backend with the generated env file:

```bash
uv run heterarchy-alexandria serve \
  --env-file "$HOME/.hermes/heterarchy-alexandria/.env" \
  --host 127.0.0.1 \
  --port 8000
```

## Install Obsidian and the side-pane plugin

```bash
brew install --cask obsidian
cd backend
uv run heterarchy-alexandria obsidian install-local \
  --vault-path "$HOME/Desktop/Alexandria" \
  --plugin-install-mode copy
```

Enable **Alexandria Librarian** in Obsidian Community plugins. Keep the backend running before using the pane.

## Capture memory, skill, and prompt artifacts

Use Obsidian Markdown as the canonical recall surface:

```bash
cd backend
uv run heterarchy-alexandria obsidian capture "Browser Verification Skill" \
  --body-file ./skill.md \
  --type skill \
  --project heterarchy-alexandria

uv run heterarchy-alexandria obsidian capture "Release Review Prompt" \
  --body-file ./prompt.md \
  --type prompt \
  --prompt-kind template

uv run heterarchy-alexandria obsidian reindex
```

`obsidian capture` is limited to `memory_compact`, `skill`, and `prompt` so imports remain migration-safe. SQLite is rebuilt from Markdown; it is not the canonical artifact store.

## Docker Compose

```bash
docker compose up --build
```

The backend is published on `127.0.0.1:8000`.

## Hermes assets

```bash
cd backend
uv run heterarchy-heterarchy-alexandria onboard
```

Skill/prompt library persistence is no longer SQLite CRUD. Keep reusable assets as Markdown/Obsidian notes with `obsidian capture` or `obsidian save`; search them with `obsidian search` after reindex.
