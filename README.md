<p align="center">
  <img src="./docs/assets/h_lib.png" alt="heterarchy-alexandria library cover" width="100%" />
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.14%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="https://docs.astral.sh/uv/"><img alt="uv" src="https://img.shields.io/badge/uv-0.8.4-654FF0?logo=astral&logoColor=white"></a>
  <a href="https://fastapi.tiangolo.com/"><img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.136.1-009688?logo=fastapi&logoColor=white"></a>
  <a href="https://docs.pydantic.dev/"><img alt="Pydantic" src="https://img.shields.io/badge/Pydantic-2.13.4-E92063?logo=pydantic&logoColor=white"></a>
  <a href="https://www.sqlalchemy.org/"><img alt="SQLAlchemy" src="https://img.shields.io/badge/SQLAlchemy-2.0.49-D71F00"></a>
  <a href="https://modelcontextprotocol.io/"><img alt="MCP" src="https://img.shields.io/badge/MCP-1.27.1-5B5BD6"></a>
  <a href="https://github.com/heterarchy-systems/heterarchy-alexandria/actions/workflows/backend.yml"><img alt="Backend CI" src="https://github.com/heterarchy-systems/heterarchy-alexandria/actions/workflows/backend.yml/badge.svg"></a>
  <a href="./LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
</p>

# heterarchy-alexandria
`heterarchy-alexandria` is the durable memory and knowledge layer of the HETERARCHY platform: a FastAPI + MCP backend for agent long-term memory, memory compaction, Obsidian Markdown storage, retrieval, and PostgreSQL-backed graph projection with Rust compute.

Removed product surfaces stay removed. Obsidian Markdown is the human-facing source of truth; PostgreSQL is the operational, lexical-search, pgvector retrieval, and persistent graph store.

```text
Obsidian Markdown = canonical notes people can read and edit
PostgreSQL = operational state + rebuildable lexical/vector indexes + persistent graph rows
Rust graph compute = deterministic graph projection, traversal, and candidate selection
heterarchy-alexandria = HETERARCHY memory/knowledge service + FastAPI backend + MCP endpoint
```

## Role in HETERARCHY

`heterarchy-alexandria` owns durable agent memory, human-readable knowledge, recall/search indexes, memory compaction, and graph projection. It is intentionally a memory/knowledge service rather than a general agent orchestrator or model runtime, so other HETERARCHY components can depend on it through explicit interfaces instead of sharing its storage internals.

### Naming

The repository, Python distribution, CLI, runtime identity, and persistent internal namespaces use `heterarchy-alexandria`. MCP tools intentionally keep the `alexandria_*` namespace, and existing `ALEXANDRIA_*` / `SERVICE_ALEXANDRIA_*` configuration names remain unchanged.

## Current scope

`heterarchy-alexandria` currently exposes an MCP-first memory, recall, and knowledge-maintenance surface:

- FastAPI backend on `127.0.0.1:8000`
- Streamable HTTP MCP endpoint at `POST /mcp/`
- Minimal package CLI for launching MCP and checking memory readiness
- MCP tools for Context Vault recall, RAG Context Packs, Memory Compact lifecycle, and Obsidian note/vault search, read, save, reindex, and safe move operations
- PostgreSQL-backed operational storage for memory/reconciliation state, Local MCP OAuth, rebuildable Obsidian/Context lexical and pgvector indexes, and persistent graph rows
- Obsidian-backed Markdown notes under `SERVICE_OBSIDIAN_VAULT_PATH`

Ordinary agents can use `recall`, `verified_upsert`, `relate`, `memory_cycle`,
`verify`, and managed-spec preparation/completion. These typed composites reuse
the existing note, retrieval, graph, reconciliation and recovery authorities.
See the [agent memory operation guide](docs/agent-memory-platform.md) for retry,
source/projection, temporal and trust-boundary semantics.

Removed legacy surfaces stay removed by contract tests:

- Next.js/frontend runtime and frontend CI
- standalone product/operator CRUD CLI commands
- SQLite library item CRUD, category/folder management, and `app/library` package code
- SQLite-backed skill/prompt/harness CRUD
- MinIO/object-storage archive/import/provider/health surfaces
- public Context Vault lint/manual-save routes

## Quick start

Runtime settings live in `module_setting_envs/{feature}_settings.env`, with
six matching Config modules under `backend/app/platform/config/`:
`app`, `mcp`, `memory`, `vault`, `database`, and `redis`.
Copy each adjacent `*_settings.env.example` to `*_settings.env` and set your
deployment values. The real files are gitignored; the examples contain no
private credentials. Existing private `.env` values must be migrated into their
feature file; application Config models no longer read the root or working-directory
`.env` as a fallback.

Every Config field requires an explicit value; use the literal `null` only for
nullable fields. Process environment variables override the feature env file.
MCP API and MCP auth use separate typed models in `mcp_config.py`; Redis cache
and maintenance queue likewise share one Redis file and one `SERVICE_REDIS_URL`.
The required Hugging Face token file path is `SERVICE_RAG_EMBEDDING_TOKEN_PATH`
in `memory_settings.env`.

Store the Compose database settings in the gitignored project `.env`. Compose
does not contain database passwords or construct `DATABASE_URL` from tracked
defaults:

```dotenv
ALEXANDRIA_POSTGRES_DB=alexandria
ALEXANDRIA_POSTGRES_USER=postgres
ALEXANDRIA_POSTGRES_PASSWORD=replace-with-a-private-local-password
```

Compose maps the private `ALEXANDRIA_POSTGRES_*` values into the official
PostgreSQL container's `POSTGRES_*` variables. Put `DATABASE_URL` in
`module_setting_envs/database_settings.env`; the backend reads that value directly and normalizes generic `postgresql://` or `postgres://` schemes to the
installed asyncpg SQLAlchemy driver. Keep the URL database, user, password, and
the Compose network host `postgres` consistent with those values.

Run the backend with Docker Compose:

```bash
docker compose up --build
```

### PostgreSQL backup and restore drill

PostgreSQL backup and restore use repository scripts outside the FastAPI
process. The backup script creates an encrypted `pg_dump` archive and manifest;
the restore-drill script verifies the archive by restoring it into a temporary
PostgreSQL database.

Set a private passphrase in the local shell, create an encrypted backup, and
then verify it with a non-destructive restore drill:

```bash
export ALEXANDRIA_POSTGRES_BACKUP_PASSPHRASE='replace-with-a-private-passphrase'
./scripts/postgres-backup.sh
./scripts/postgres-restore-drill.sh <backup-id-or-backup-directory>
unset ALEXANDRIA_POSTGRES_BACKUP_PASSPHRASE
```

The version-2 backup manifest records the Alembic revision, public-table count,
pgvector presence, and plaintext/encrypted hashes. The restore drill requires
those invariants to match and confirms that its temporary database was removed
before publishing a `VERIFIED` report. This archive covers PostgreSQL only;
back up the canonical Obsidian Vault and `backend/data/.alexandria-recovery`
with the host filesystem policy as separate durable assets.

Graph projection has no separate database service or credential profile.
PostgreSQL `obsidian_files` and `obsidian_edges` are the persistent graph source,
while Rust owns deterministic projection, traversal, and candidate-selection
compute. Each process lazily cold-loads its app-lifetime projection cache from
PostgreSQL on its first graph-state read. An explicit rebuild also stages and
activates the projection in the serving process handling that request. The
`postgresql-current` run ID used for a cold-loaded state is a label, not a source
revision. Automatic publication between serving processes and cross-process
cache convergence have not been established, so a rebuild or status read from
one process does not prove another process's cache state.

After schema changes or vault-wide link changes, rebuild the canonical index first and then refresh the graph projection:

```bash
cd backend
uv run alembic upgrade head
curl -X POST http://127.0.0.1:8000/obsidian/index/rebuild
curl -X POST http://127.0.0.1:8000/obsidian/graph/projection/rebuild
curl http://127.0.0.1:8000/obsidian/graph/projection/status
```

Graph evidence, lineage, related-note reads, traversal, and impact analysis all derive from this PostgreSQL + Rust path; there is no optional graph read-model mode.

### Redis operational acceleration

Redis is an internal acceleration and delivery layer, not canonical storage and
not the cross-process lock authority. PostgreSQL advisory locks remain the final
maintenance exclusion boundary. The local Compose Redis instance uses AOF
`everysec`, a removable named volume, a 256 MiB cap, and `noeviction` so pending
Streams jobs are never silently discarded under memory pressure.

The first queued workload is embedding reindex: the API submits a deduplicated
Redis Streams job, one separate worker consumes at concurrency `1`, each job is
bounded to `250` chunks by default, and failures are retried up to `3` attempts
before a dead-letter entry is recorded. Queue submission is limited to `6` new
jobs per caller per `60` seconds, while identical manual/scheduler submissions
reuse the existing job for a `60` second cooldown.

Disposable status caches use the following TTLs: operational readiness `5`
seconds, graph projection status `5` seconds, and embedding health `10` seconds.
Direct outbound OpenAI calls consume a Redis fixed-window permit before network
activity; the default budget is `60` calls per provider-call scope per `60`
seconds. Redis failure disables queued maintenance and, by default, fails closed
for outbound provider calls, while canonical Markdown and PostgreSQL-backed core
memory remain independent.

Graph retrieval remains backed by PostgreSQL `obsidian_files`/`obsidian_edges`
and the Rust graph compute layer. Its process-local cache follows the lazy
cold-load and explicit rebuild activation behavior described above.

Keep the PostgreSQL schema and canonical Obsidian index current before graph diagnostics or explicit graph rebuilds:

```bash
cd backend
uv run alembic upgrade head
curl -X POST http://127.0.0.1:8000/obsidian/index/rebuild
curl -X POST http://127.0.0.1:8000/obsidian/graph/projection/rebuild
curl http://127.0.0.1:8000/obsidian/graph/projection/status
```

Graph rebuild responses are concise by default: `issue_total` and `issue_counts` summarize non-fatal source diagnostics, while `errors` contains only operation failures. Missing or ambiguous link targets are skipped instead of entering the active projection. Request a bounded sample only when investigating diagnostics:

```bash
curl -X POST \
  'http://127.0.0.1:8000/obsidian/graph/projection/rebuild?include_issue_details=true&issue_limit=100'
```

Vault reindex, embedding rebuild/reindex, and graph projection rebuild share one fail-fast maintenance lane. A competing maintenance request returns HTTP `409`; retry it after the active operation finishes rather than running rebuilds in parallel.

Or run it locally from `backend/`:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Required local secret:

```bash
export SERVICE_MCP_LOCAL_APPROVAL_KEY="replace-with-at-least-32-characters"
```

Docker Compose mounts `module_setting_envs/` read-only; Config models read their
matching files directly. Image-baked build provenance remains in the process
environment and overrides file values. The root `.env` remains for Compose interpolation
(database-container credentials, host paths and build settings), not application
Config loading. Explicit Compose mount-path values, image provenance, and
`runtime-performance.env` retain their process-environment precedence.

Useful Obsidian storage settings:

```bash
export SERVICE_OBSIDIAN_VAULT_PATH="$HOME/Desktop/Alexandria"
export SERVICE_ALEXANDRIA_OBSIDIAN_ROOT="."
export SERVICE_MEMORY_COMPACT_NOTE_DIR="Memory Compacts"
```

Use `SERVICE_ALEXANDRIA_OBSIDIAN_ROOT="."` when the vault itself is the Alexandria workspace. This avoids a nested `Alexandria/Alexandria` layout.

After the backend is running, verify the Memory Steward/Vault maintenance bridge with the
package CLI, not Makefile operational wrappers. Install/sync once, then use
`--no-sync` for parseable JSON stdout:

```bash
cd backend
make install-local
uv run --no-sync --no-editable heterarchy-alexandria memory-steward check \
  --project heterarchy-alexandria \
  --refresh-compact \
  --summary
```

The command returns parseable JSON and repairs only stale or missing CURRENT
Memory Compacts. A healthy local bridge returns `ok: true`, empty `warnings`,
healthy RAG fields, `review_queue_total: 0`, and a current compact id/age.
When attention is needed, the summary includes `next_actions_count`,
`next_action`, `next_action_tool`, `review_auto_move_candidates`, and
`review_manual_required` so an agent can choose the next safe maintenance
operation without reading a long diagnostic body.

## MCP endpoint

The FastAPI app exposes the Streamable HTTP MCP endpoint at:

```text
http://127.0.0.1:8000/mcp/
```

`heterarchy-alexandria` supports three explicit MCP authentication modes:

- `none`: default localhost-only mode; no bearer token is required.
- `local_oauth2`: the service runs its own Authorization Code + PKCE server,
  issues rotating access/refresh tokens, and asks the local operator to approve
  each connection in the browser.
- `oauth2`: the service only verifies JWT bearer tokens issued by an external
  authorization server through issuer/audience/JWKS configuration.

The OpenAI Codex OAuth routes under `/settings/connections/{provider_id}/oauth/*`
serve a different direction: they authorize the backend to call a provider. MCP
OAuth authorizes ChatGPT or another MCP client to call `heterarchy-alexandria`.

For the default `none` mode, keep the backend bound to `127.0.0.1` and connect
an MCP client directly to the URL above. No custom operator header is required.

To enable service-issued OAuth for a public HTTPS endpoint, configure:

```bash
export SERVICE_MCP_LOCAL_APPROVAL_KEY="$(openssl rand -base64 32)"
export SERVICE_SECRET_ENCRYPTION_KEY="$(openssl rand -base64 32)"
export SERVICE_MCP_AUTH_MODE="local_oauth2"
export SERVICE_MCP_OAUTH_ISSUER="https://your-mcp-host.example"
export SERVICE_MCP_OAUTH_RESOURCE="https://your-mcp-host.example/mcp"
```

Then connect ChatGPT to:

```text
https://your-mcp-host.example/mcp
```

The client discovers `/register`, `/authorize`, `/token`, `/revoke`, and the
OAuth metadata automatically. During connection, the service opens `/approve`;
open `http://127.0.0.1:8000/connect` on the backend host, create one pairing
code, and enter it on the approval page. Pairing codes are single-use and
short-lived. Authorization codes and access/refresh tokens are stored only as
SHA-256 lookup hashes; dynamic client secrets are encrypted with the configured
`SERVICE_SECRET_ENCRYPTION_KEY`.

Public hosts expose only the MCP/OAuth protocol routes and `/health/live`.
Operator surfaces such as `/connect`, `/settings/connections`, `/operations`,
API documentation, and ordinary backend REST routes remain localhost-only.
Use `http://127.0.0.1:8000/connect` for local administration; do not publish the
Hub itself as the MCP endpoint.

For an external OAuth/JWKS issuer instead, use `SERVICE_MCP_AUTH_MODE=oauth2`
and configure `SERVICE_MCP_OAUTH_ISSUER`, `SERVICE_MCP_OAUTH_AUDIENCE`, and
`SERVICE_MCP_OAUTH_JWKS_URL`.

After changing or reinstalling the backend, an MCP `tools/list` smoke check should
include the Memory Steward and Vault maintenance tools:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria mcp smoke-tools
```

```text
alexandria_memory_steward_readiness
alexandria_memory_steward_refresh_current_compact
alexandria_vault_inventory
alexandria_vault_path_search
alexandria_vault_move_plan
alexandria_vault_apply_moves
```

Memory maintenance and explicit vault operations are exposed as narrow MCP capabilities. Provider/profile selection, external delegation, and autonomous skill-acquisition runtime are not part of the current requesting-agent surface.

To check both MCP tool exposure and Memory Steward readiness in one script-friendly
JSON result, run:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria memory-steward check \
  --project heterarchy-alexandria
```

For a status-only JSON result, including MCP endpoint/tool count, tool exposure,
required Memory Steward/Vault MCP tool names, RAG health, review queue total,
automatic/manual curation counts, the current compact id/age, and the first
recommended maintenance action, add `--summary`:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria memory-steward check \
  --project heterarchy-alexandria \
  --summary
```

For startup automation that also repairs only stale or missing CURRENT compacts,
add `--refresh-compact`:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria memory-steward check \
  --project heterarchy-alexandria \
  --refresh-compact \
  --summary
```

A minimal JSON-RPC initialize request for localhost `none` mode is:

```bash
curl -sS http://127.0.0.1:8000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"initialize",
    "params":{
      "protocolVersion":"2025-06-18",
      "capabilities":{},
      "clientInfo":{"name":"curl-smoke","version":"0.1.0"}
    }
  }'
```

## Memory Steward CLI and vault maintenance API

The current package CLI exposes the `mcp` and `memory-steward` command groups.
Use their help output for the supported commands; there is no `vault` or
`obsidian` CLI group.

Run a one-shot readiness check against the local backend:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria memory-steward readiness \
  --project heterarchy-alexandria
```

The `memory-steward readiness` command reports readiness for the selected
project. Vault maintenance is exposed through the FastAPI API and MCP tools,
not through separate CLI commands:

| Operation | HTTP API | MCP tool |
| --- | --- | --- |
| Inventory managed notes | `POST /obsidian/vault/inventory` | `alexandria_vault_inventory` |
| Search managed paths | `POST /obsidian/vault/path-search` | `alexandria_vault_path_search` |
| Plan safe moves | `POST /obsidian/vault/move-plan` | `alexandria_vault_move_plan` |
| Apply explicit safe moves | `POST /obsidian/vault/apply-moves` | `alexandria_vault_apply_moves` |

Review the move-plan response before sending explicit moves to the apply route.

Connect an MCP client to the endpoint documented above, or inspect the local
FastAPI OpenAPI document for request schemas when it is enabled.

Use preflight in scripts or agent startup checks. It prints the same JSON-shaped
readiness evidence, returns exit code `0` when ready, and returns exit code `2`
when Memory Steward still needs attention:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria memory-steward preflight \
  --project heterarchy-alexandria
```

Plan a CURRENT Memory Compact refresh without mutating the vault:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria memory-steward refresh-current-compact \
  --project heterarchy-alexandria
```

Apply the refresh only when the plan says `refresh_required: true`, or when an
operator intentionally passes `--force`:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria memory-steward refresh-current-compact \
  --project heterarchy-alexandria \
  --apply
```

For a startup check that may repair only stale or missing CURRENT compacts, use:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria memory-steward preflight \
  --project heterarchy-alexandria \
  --refresh-compact
```

This passes `--refresh-compact`, but it remains a no-op when the CURRENT compact
is already fresh (`refresh_required: false`, `created: null`). It only creates a
new CURRENT compact when readiness reports a missing, stale, or timestamp-less
compact. Use `--max-compact-age-days 14` to tighten freshness during a check.

## Canonical memory, skills, and prompts

Reusable artifacts live as Obsidian notes, not database library rows. PostgreSQL keeps operational memory/reconciliation and retrieval metadata, while the human-editable source of truth remains Markdown in the vault.

Memory Compact lifecycle APIs write Markdown under `SERVICE_MEMORY_COMPACT_NOTE_DIR`. Rebuild the Obsidian index with:

```bash
curl -sS -X POST http://127.0.0.1:8000/obsidian/index/rebuild
```

If PostgreSQL retrieval indexes are rebuilt, Markdown can repopulate note, chunk, edge, lexical, and vector projections. Local MCP OAuth and other operational state that is not derived from Markdown require normal PostgreSQL backups.

## Graph edges and related notes

Reindex rebuilds PostgreSQL `obsidian_files` and `obsidian_edges` from canonical Markdown. Rust computes the deterministic projection, traversal, and graph candidate selection from those typed rows; related-note and graph evidence/lineage/impact reads use the active rebuildable projection backed by that PostgreSQL source.

HTTP additions include related-note retrieval:

```text
GET  /obsidian/notes/by-path/related?path=<path>
GET  /obsidian/notes/{note_id}/related
```

Vault maintenance is exposed separately through explicit inventory, path-search, move-plan, and apply-moves operations under `/obsidian/vault/...`. No separate collaboration workflow runtime or SQLite checkpoint database is part of the current product.

## Local development

Backend development uses `uv` and the backend Makefile:

```bash
cd backend
uv sync
make format_check
make type_checking
make mechanical_check
make test
```

`make mechanical_check` is intentionally database-free. `make test` starts an
ephemeral localhost-only PostgreSQL/pgvector container on a random host port,
runs the full test suite against a session-owned test database, and removes the
container on exit. It does not depend on the runtime Compose `postgres` network
alias or the private repository `.env`.

Run the GitHub Actions parity gate from the repository root:

```bash
make ci
```

`make ci` runs Python and Rust validation, including a no-editable package CLI
smoke check for `heterarchy-alexandria` and the ephemeral-PostgreSQL test contract.
CI requires no private `.agents` bundle. Python code-contract checks and their
source-scope/profile configuration live in `backend/scripts/verification/`;
Rust workspace, dependency, effect-boundary, and compute-authority checks live in
`native/xtask/`. Private agent rules, skills, and their bundle-integrity checks
remain local development tools.

Health check:

```bash
curl http://127.0.0.1:8000/health/live
```
