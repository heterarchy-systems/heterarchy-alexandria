# Alexandria Librarian Obsidian Plugin

Minimal Obsidian community-plugin bridge for the local heterarchy-alexandria backend.

## Install locally

1. Run the heterarchy-alexandria backend on `http://127.0.0.1:8000`.
2. Install this folder into your vault with the CLI:

   ```bash
   cd backend
   uv run heterarchy-alexandria obsidian install-local \
     --vault-path "<vault>" \
     --plugin-install-mode copy
   ```

   Copy mode avoids repo-local `data.json` writes. Use `symlink` only while developing this plugin.

3. In Obsidian, enable community plugins and enable **Alexandria Librarian**.
4. Run command palette action **Ask Alexandria Librarian**.

## What it does

- Opens a right-side `ItemView` chat pane.
- Defaults to **Whole vault** scope: the librarian searches indexed memory, skills, prompts, plans, and context notes before citing source notes.
- Can switch to active-note or selection context when the current note should be pinned.
- Lets you choose note type filters and source count from the pane.
- Keeps a local in-pane conversation history for the current Obsidian session.
- Calls `POST /obsidian/librarian/workflows` by default for LangGraph approval, or `POST /obsidian/librarian/ask` when workflow mode is disabled.
- Renders the Markdown answer, source wikilinks, workflow status badges, and a separate GPT OAuth librarian result panel.
- Provides an in-pane GPT OAuth connection card: check status, start device login, open the verification page, copy the user code, poll after login, and refresh the backend token.
- Shows related notes from `GET /obsidian/notes/by-path/related`.
- Can append the answer to the current note.
- Can add managed Alexandria source wikilinks to the current note.
- Can create context, skill draft, or prompt template notes through `POST /obsidian/notes`.
- Can resume approved LangGraph action cards, including GPT/OAuth librarian delegation, without storing OAuth tokens.
- Can configure the backend Obsidian vault destination from plugin settings through `PUT /obsidian/settings/vault`.

## Backend vault destination

If the backend is saving notes into the generated `backend/data/obsidian-vault`
instead of your real Obsidian vault:

1. Open **Alexandria Librarian** plugin settings.
2. Set **Operator API key**.
3. Under **Backend Obsidian vault**, click **Use current vault**.
4. Keep **Alexandria root in vault** as `.` when the current vault root is already
   the Alexandria vault, or set it to `Alexandria` to save under an
   `Alexandria/` folder.
5. Click **Apply to backend**. The backend persists the path, initializes folders,
   and reindexes without requiring a restart.

## GPT OAuth from Obsidian

1. In plugin settings, set **Operator API key** to the local backend `ALEXANDRIA_OPERATOR_API_KEY`; OAuth lifecycle endpoints are protected.
2. Set **Preferred provider id** to `codex-oauth` or another backend provider id/name.
3. If the provider/profiles do not exist yet, bootstrap them once from the CLI:

   ```bash
   cd backend
   uv run heterarchy-alexandria librarian bootstrap-obsidian-oauth --provider-name codex-oauth
   ```

4. In the Alexandria Librarian pane, use **Start OAuth login**. The plugin opens the provider verification page and shows the user code.
5. Complete login in the browser, then click **Poll after login**. The backend stores the OAuth token; Obsidian stores only provider/profile preferences.
6. Enable **Ask OAuth librarian** when asking a question or approving a LangGraph `ask_oauth_librarian` action.

No npm build step is required; `main.js`, `manifest.json`, and `styles.css` are loaded directly by Obsidian.
