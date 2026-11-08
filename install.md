# Install

heterarchy-alexandria installs as a backend/CLI/MCP service. The old frontend runtime has been removed.

## Requirements

- GIL-enabled CPython `>=3.14` through `uv` (the repository pin is 3.14.7)
- macOS Homebrew Cask only if you want Codex to install Obsidian locally
- Obsidian for the human-facing Markdown vault

## Redis maintenance queue settings

`SERVICE_REDIS_MAINTENANCE_QUEUE_ENABLED` controls maintenance job submission and
worker processing, and defaults to `true`. Setting it to `false` disables only
the maintenance queue. `SERVICE_REDIS_URL` continues to configure the shared
Redis client used by API caches and provider rate limits.

Queue settings are owned by the maintenance queue configuration. The canonical
worker controls include `SERVICE_REDIS_MAINTENANCE_WORKER_CONCURRENCY`,
`SERVICE_REDIS_MAINTENANCE_BLOCK_MILLISECONDS`,
`SERVICE_REDIS_MAINTENANCE_RETRY_IDLE_SECONDS`,
`SERVICE_REDIS_MAINTENANCE_MAX_ATTEMPTS`,
`SERVICE_REDIS_MAINTENANCE_STATUS_TTL_SECONDS`, and
`SERVICE_REDIS_MAINTENANCE_MAX_STREAM_LENGTH`. Submission behavior uses
`SERVICE_REDIS_MAINTENANCE_DEDUP_COOLDOWN_SECONDS`,
`SERVICE_REDIS_MAINTENANCE_SUBMISSION_LIMIT`, and
`SERVICE_REDIS_MAINTENANCE_SUBMISSION_WINDOW_SECONDS`. Worker embedding
parallelism uses `SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS`.

These older names were not consumed by the queue runtime and are obsolete:
`SERVICE_REDIS_MAINTENANCE_POLL_INTERVAL_MS`,
`SERVICE_REDIS_MAINTENANCE_CLAIM_IDLE_MS`,
`SERVICE_REDIS_MAINTENANCE_JOB_MAX_ATTEMPTS`,
`SERVICE_REDIS_MAINTENANCE_JOB_STATUS_TTL_SECONDS`,
`SERVICE_REDIS_MAINTENANCE_STREAM_MAX_LENGTH`,
`SERVICE_REDIS_MAINTENANCE_MANUAL_COOLDOWN_SECONDS`, and
`SERVICE_REDIS_MAINTENANCE_SCHEDULER_COOLDOWN_SECONDS`. Remove them from
operator environment files. There are no separate manual and scheduler cooldown
controls; identical-job deduplication uses
`SERVICE_REDIS_MAINTENANCE_DEDUP_COOLDOWN_SECONDS`.

## Development checkout hygiene

Keep the `uv` project environment and Python bytecode outside a synced checkout
so stale filesystem entries do not slow collection. The repository Makefiles
and PostgreSQL test runner use the bytecode path below when
`PYTHONPYCACHEPREFIX` is unset.

```bash
export UV_PROJECT_ENVIRONMENT="${XDG_CACHE_HOME:-$HOME/.cache}/heterarchy-alexandria/venv"
export PYTHONPYCACHEPREFIX="${XDG_CACHE_HOME:-$HOME/.cache}/heterarchy-alexandria/pycache"
cd backend
uv sync --locked --no-editable
```

Run the local repository gate from the checkout root:

```bash
cd ..
make ci
```

The GitHub Actions backend job uses the same repository gate after syncing
dependencies with:

```bash
cd backend
uv sync --group dev --reinstall-package heterarchy-alexandria
cd ..
make ci
```

## Local embedding model artifacts

Python acquires and streams the five multilingual-E5 model assets; Rust initializes
FastEmbed and owns inference. Initialization is lazy and shared within each
provider. Later queries and batches call that provider's native session directly,
without a process-global session registry, native cache lookup or model downloading.

Runtime ABI 4 prepares ONNX only after Python validates that asset's bytes and
descriptor evidence. Its anonymous input mapping is released before tokenizer
transfer. All remaining asset and snapshot checks must succeed before the provider
publishes an inference session; later failures discard the pending session.
The internal `heterarchy-alexandria-model-buffer` crate reuses the existing locked
`libc` dependency. Its narrowly approved mapping boundary is documented in
`native/crates/heterarchy-alexandria-model-buffer/SAFETY.md`; other workspace crates
retain the unsafe-code prohibition. Rebuild the extension with the Python source
when upgrading this runtime ABI.

For large dense FLOAT initializers, Rust builds a transient model representation
and validates its tensor registrations against the original names, dimensions and
types. The original model's external-resource checks and file hashes remain in
force. Weights and default inference options are preserved; transformed models
are not written to the cache. The vendored SDK patch also reuses the existing
`zerocopy` package for initialized tensor buffers.

The model cache keeps the existing Hugging Face `refs/main`, `snapshots`, and
`blobs` layout. A complete cached snapshot is read offline without creating cache
files or reading credentials. Missing files in an existing snapshot are fetched
at that same commit. A fresh cache resolves `main` once and pins every download
to that commit; conflicting cached evidence fails without selecting another revision.

Configure `module_setting_envs/memory_settings.env` explicitly. Cache-root
precedence remains `HF_HOME`, then `SERVICE_RAG_EMBEDDING_CACHE_DIR`, then the
required `FASTEMBED_CACHE_DIR`; there is no additional hardcoded cache fallback.
`HF_HOME` is used directly without adding `hub`. Paths retain literal filesystem
semantics. `HF_ENDPOINT` and `SERVICE_RAG_EMBEDDING_TOKEN_PATH` are required
settings; acquisition reads only that selected token file, and removes
authorization on cross-origin redirects.

Write `ORT_LOAD_CONFIG_FROM_MODEL=0` to keep model-side configuration disabled.
Model-defined session
options, external tensor files and `EPContext` operators are outside the reviewed
embedded CPU model contract. Disabled and test embedding providers do not load
these artifact settings.

The persisted embedding fingerprint still identifies the provider, model name
and inference policy, rather than a model-file digest. Preserving a cached
snapshot preserves its bytes; a lost cache followed by fresh acquisition cannot
by itself establish compatibility with previously stored vectors. Acquisition
does not automatically reindex those vectors. The provider retains one fully
initialized session for its own lifetime. Separate root containers/providers own
independent sessions; request services within a root share its Singleton provider.

## Configure the Obsidian vault

Set the vault path before starting the backend. The vault remains the canonical
Markdown note store; PostgreSQL owns persistent runtime state and the indexes.
SQLite is not a runtime database or compatibility fallback.

```bash
export SERVICE_OBSIDIAN_VAULT_PATH="$HOME/Desktop/Alexandria"
export SERVICE_ALEXANDRIA_OBSIDIAN_ROOT="."
export SERVICE_MEMORY_COMPACT_NOTE_DIR="Memory Compacts"
```

Use `SERVICE_ALEXANDRIA_OBSIDIAN_ROOT="."` when Alexandria-managed notes should
live directly at the vault root.

## Run the backend

For the local Docker deployment:

```bash
docker compose up --build
```

The backend is published on `127.0.0.1:8000`. For a local `uv` run, configure
the six private `module_setting_envs/*_settings.env` files from their adjacent
examples. Set PostgreSQL in `database_settings.env`; process environment values
can override these files. The root `.env` is only for Compose interpolation.
Then run:

```bash
cd backend
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Initialize a new vault only when needed, then rebuild its index:

```bash
curl -X POST http://127.0.0.1:8000/obsidian/init
curl -X POST http://127.0.0.1:8000/obsidian/index/rebuild
```

The current graph projection API is `POST /obsidian/graph/projection/rebuild`
and `GET /obsidian/graph/projection/status`. These explicit routes use the
PostgreSQL index and Rust graph compute path.

## MCP and package CLI

The FastAPI app exposes Streamable HTTP MCP at:

```text
http://127.0.0.1:8000/mcp/
```

Configure the MCP client with that endpoint. The installed CLI currently exposes
the `mcp` and `memory-steward` command groups. Inspect the supported commands
and options with:

```bash
cd backend
uv run --no-sync --no-editable heterarchy-alexandria --help
uv run --no-sync --no-editable heterarchy-alexandria mcp --help
uv run --no-sync --no-editable heterarchy-alexandria memory-steward --help
```

After the backend is running, run a Memory Steward check with:

```bash
uv run --no-sync --no-editable heterarchy-alexandria memory-steward check \
  --project heterarchy-alexandria \
  --summary
```

Vault maintenance is available through the current API and MCP tools:

| Operation | HTTP API | MCP tool |
| --- | --- | --- |
| Inventory managed notes | `POST /obsidian/vault/inventory` | `alexandria_vault_inventory` |
| Search managed paths | `POST /obsidian/vault/path-search` | `alexandria_vault_path_search` |
| Plan safe moves | `POST /obsidian/vault/move-plan` | `alexandria_vault_move_plan` |
| Apply explicit safe moves | `POST /obsidian/vault/apply-moves` | `alexandria_vault_apply_moves` |

Review the move-plan response before sending explicit moves to the apply route.

For request schemas, consult the local FastAPI OpenAPI document when enabled.

## Install Obsidian (optional)

```bash
brew install --cask obsidian
```
