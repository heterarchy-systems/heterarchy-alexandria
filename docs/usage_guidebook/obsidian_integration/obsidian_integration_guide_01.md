---
alexandria_type: job_plan
id: guide_obsidian_integration_01
tags:
  - alexandria
  - obsidian
  - guidebook
status: active
created_at: "2026-05-25"
source: codex
---

# Obsidian Integration Guide 01 — Vault, PostgreSQL Index, Rust Graph

heterarchy-alexandria treats Obsidian Markdown as the human-facing durable knowledge store.
PostgreSQL owns the indexed source and graph state; Rust owns deterministic graph compute.

```text
Obsidian Markdown = canonical notes
PostgreSQL = search/index/graph source
heterarchy-alexandria = backend/CLI/MCP protocol
Memory Steward = compact and reconciliation lifecycle
```

## 1. Install and open Obsidian

On macOS, install Obsidian with Homebrew Cask:

```bash
brew install --cask obsidian
```

You can use either:

- the generated heterarchy-alexandria vault at `~/.hermes/heterarchy-alexandria/data/obsidian-vault`; or
- an existing Obsidian vault such as `~/Desktop/Alexandria`.

The local smoke test used `/Users/imhaneul/Desktop/Alexandria` with Alexandria root `.`.

## 2. Configure heterarchy-alexandria

### Generated vault

Terminal 1:

```bash
cd backend
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000
```

Terminal 2, after the backend is running:

```bash
cd backend
curl -fsS -X POST http://127.0.0.1:8000/obsidian/init
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild
```

`uv run alembic upgrade head` applies Alembic before the first backend/Obsidian call, preventing missing-table errors on `/obsidian/init`.

The generated `.env` includes:

```text
SERVICE_OBSIDIAN_VAULT_PATH=<hermes-home>/heterarchy-alexandria/data/obsidian-vault
SERVICE_ALEXANDRIA_OBSIDIAN_ROOT=Alexandria
SERVICE_MEMORY_COMPACT_NOTE_DIR=Alexandria/Memory Compacts
```

### Existing `Alexandria` vault

Use this when Obsidian already has a vault at `~/Desktop/Alexandria` and you want the vault itself to be the Alexandria workspace:

```bash
cd backend
export SERVICE_OBSIDIAN_VAULT_PATH="$HOME/Desktop/Alexandria"
export SERVICE_ALEXANDRIA_OBSIDIAN_ROOT="."
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The generated `.env` then includes:

```text
SERVICE_OBSIDIAN_VAULT_PATH=<home>/Desktop/Alexandria
SERVICE_ALEXANDRIA_OBSIDIAN_ROOT=.
SERVICE_MEMORY_COMPACT_NOTE_DIR=Memory Compacts
```

Root `.` prevents a nested `Alexandria/Alexandria` layout.

## 3. Vault layout

Generated-vault mode manages an `Alexandria/` folder inside the vault:

```text
Alexandria/
  START_HERE.md
  Contexts/
  Memory Compacts/
  Skills/
  Prompts/
  Jobs/
```

Existing-vault root mode places the same folders directly under the vault root:

```text
START_HERE.md
Contexts/
Memory Compacts/
Skills/
Prompts/
_Ops/
Jobs/
```

Move files inside Obsidian if needed; Alexandria identifies official notes by frontmatter `id`, not only by path.

## 4. Frontmatter contract

Every Alexandria-managed note starts with YAML frontmatter:

```yaml
---
alexandria_type: context
id: ctx_example
tags:
  - alexandria
status: active
created_at: "2026-05-25T12:00:00Z"
source: mcp
---
```

Supported `alexandria_type` values include `context`, `memory_compact`, `skill`, `prompt`, `job_plan`, and `implementation_history`.

Notes without this frontmatter can stay in the vault, but reindex skips them as non-Alexandria notes.

Obsidian Properties stores these values as YAML. Prefer simple scalar values and
block lists because those are the property shapes the Obsidian UI can edit
reliably. Quote wikilinks in Properties, and treat paths inside them as
vault-root-relative:

```yaml
tags:
  - "alexandria"
  - "memory-compact"
source_ref_links:
  - "[[Contexts/Projects/heterarchy-alexandria/Source Note]]"
related:
  - "[[Skills/Active/Alexandria Library]]"
```

Nested object properties are valid YAML but are not currently supported by the
Obsidian Properties UI. Alexandria therefore retains structured `source_refs`
where a lossless machine round-trip is required and also writes the flat
`source_ref_links` list for Obsidian-native link discovery. Edit structured
legacy metadata in Source mode; use the flat link properties for new human-edited
relationships.

Reference: [Obsidian Properties](https://obsidian.md/help/properties) and
[Obsidian Internal links](https://obsidian.md/help/Linking%2Bnotes%2Band%2Bfiles/Internal%2Blinks).

## 5. HTTP and MCP examples

Search indexed notes through the registered HTTP route:

```bash
curl -fsS -X POST http://127.0.0.1:8000/obsidian/search \
  -H 'Content-Type: application/json' \
  --data '{"query":"long memory","limit":5}' | jq
```

Read a canonical note by its vault-relative path:

```bash
curl -fsS \
  'http://127.0.0.1:8000/obsidian/notes/by-path?path=START_HERE.md' | jq
```

Create or update notes through the MCP note tools, then refresh the index:

```bash
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild | jq
```

## 6. MCP tools

Agents can use MCP tools that mirror the CLI:

- `alexandria_reindex_vault`
- `alexandria_search_vault`
- `alexandria_read_note`
- `alexandria_get_related_notes`
- `alexandria_get_graph_projection_status`
- `alexandria_rebuild_graph_projection`
- `alexandria_vault_inventory`
- `alexandria_vault_move_plan`
- `alexandria_vault_apply_moves`

The intended agent flow is:

```text
search vault → read selected notes → answer/write new Markdown → reindex if needed
```

## 7. Graph relation contract

Alexandria relation frontmatter uses quoted, vault-root-relative wikilink lists
and is rendered into an Obsidian-readable managed wikilink section:

```yaml
source_ref_links:
  - "[[START_HERE]]"
derived_from: []
related: []
supersedes: []
promotes_to: []
```

```md
<!-- ALEXANDRIA-LINKS:START -->
## Alexandria Links

### Sources
- [[START_HERE]] — cites
<!-- ALEXANDRIA-LINKS:END -->
```

PostgreSQL stores the indexed `obsidian_files` and `obsidian_edges` source state. Rust computes the deterministic projection, traversal, and candidate selection; the application keeps only a bounded rebuildable projection cache. Missing and ambiguous targets remain counted non-fatal diagnostics and are excluded from the active projection.

## 8. Smoke-test evidence

The local `/Users/imhaneul/Desktop/Alexandria` vault was tested with:

```text
SERVICE_OBSIDIAN_VAULT_PATH=/Users/imhaneul/Desktop/Alexandria
SERVICE_ALEXANDRIA_OBSIDIAN_ROOT=.
```

Observed result:

- `START_HERE.md` and `Jobs/Alexandria Obsidian Smoke Test.md` were created.
- A generated smoke fixture may index only a handful of notes, while the current `/Users/imhaneul/Desktop/Alexandria` vault is larger. Recent local verification saw 95 files, indexed 79 Alexandria notes, and skipped 16 non-Alexandria files.
- Search found indexed Alexandria notes.
- The PostgreSQL/Rust projection reports graph status and related notes through the registered MCP tools and `/obsidian/graph/*` routes.

## 9. Safety rules

- Do not save raw secrets/API keys/tokens into Obsidian notes.
- Treat Obsidian Markdown as canonical; PostgreSQL indexes and projections are rebuildable.
- Resolve conflicts in Obsidian first, then run `POST /obsidian/index/rebuild` or `alexandria_reindex_vault`.
- Keep frontend/Next.js removed unless product direction explicitly changes.
