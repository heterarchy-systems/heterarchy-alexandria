# Librarian execution and embedding recovery runbook

Use this runbook when the Obsidian librarian reports missing notes while the
vault still contains relevant Alexandria notes, or when `/memory/contexts/rag/status`
returns `REINDEX_REQUIRED`.

## Safety rule

Do **not** delete the whole database to fix embedding drift. Source contexts,
Obsidian notes, and memory records are canonical. Rebuild only the embedding/vector
fields unless an operator explicitly chooses a destructive recovery path.

## Recovery sequence

1. Back up local state.

   ```bash
   cp backend/data/alexandria_hermes.db backend/data/alexandria_hermes.db.bak
   ```

2. Apply migrations.

   ```bash
   cd backend
   uv run alembic upgrade head
   ```

3. Check current retrieval fingerprint/status.

   ```bash
   uv run python -m app.cli --json context doctor-rag
   ```

   The response includes `fingerprint` and may set `embedding` to
   `REINDEX_REQUIRED` when stored chunk embeddings do not match the current
   provider/model/version/pooling/normalize/dimension fingerprint.

4. Run a soft embedding/vector rebuild.

   ```bash
   uv run python -m app.cli --json context soft-rebuild \
     --limit 1000 \
     --verification-query "known project-specific phrase" \
     --project heterarchy-alexandria
   ```

   This operation preserves source contexts, Obsidian notes, and memory rows. It
   rewrites only chunk embedding metadata/vector fields and returns before/after
   RAG status plus verification-match evidence.

5. Repeat the soft rebuild if needed.

   If the result says `after.embedding` is still `REINDEX_REQUIRED`, rerun with a
   higher limit or repeat the command until `after.embedding` becomes `HEALTHY`.

6. Run a verification query.

   ```bash
   uv run python -m app.cli --json context rag \
     "known project-specific phrase" \
     --strategy HYBRID \
     --project heterarchy-alexandria
   ```

7. Use typed librarian jobs for vault organization.

   For long vault organization tasks, use the librarian job API instead of a
   single synchronous ask request:

   ```text
   POST /obsidian/librarian/jobs
   GET  /obsidian/librarian/jobs/{job_id}
   GET  /obsidian/librarian/jobs/{job_id}/report
   ```

   Jobs are best-effort and in-process: the status registry is not durable across
   service restarts, but completed report Markdown/JSON files are durable vault
   artifacts. Jobs return a report with moved/skipped/ambiguous files,
   no-hard-delete proof, reindex status, and verification counts.

## Expected healthy status

After recovery, `/memory/contexts/rag/status` should show:

- `fts`: `HEALTHY`
- `embedding`: `HEALTHY`
- `default_strategy`: `HYBRID` when vector dependencies are available
- current `fingerprint` matching stored chunk metadata

When any configured retrieval source reports `REINDEX_REQUIRED`, vector recall is
conservatively disabled across the configured sources for that request and the
service falls back to FTS-only retrieval until all source fingerprints match.

