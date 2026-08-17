# Agent Scope Memory PRD Completion

## Scope

This record closes the heterarchy-alexandria Agent Scope Memory PRD implementation
for `SESSION`, `AGENT`, and `PROJECT` Contexts. Platform orchestration, RBAC,
automatic promotion, and other PRD non-goals remain outside this work.

## Task matrix

| Task | Requirement | Status | Evidence |
|---|---|---|---|
| T1 | Scope and identity validation across canonical save/reindex/recall | VERIFIED | Scope validation, round-trip, and strategy consistency tests |
| T2 | Obsidian identity/provenance round trip and SQLite rebuild | VERIFIED | Temporary vault/database reindex evidence |
| T3 | FTS, Vector, and Hybrid scope/lifecycle consistency | VERIFIED | Strategy recall results and lifecycle tests |
| T4 | Content hash, duplicate detection, provenance, and Context Pack | VERIFIED | Repository, Obsidian, retrieval metadata, and pack tests |
| T5 | Archive and explicit bidirectional Supersede capability | VERIFIED | Context API, MCP, canonical lifecycle, idempotency, conflict, and recall tests |
| T6 | P95 performance targets and reproducible acceptance evidence | VERIFIED | Tracked evidence package under `docs/project_remaining_work/agent-scope-memory-evidence` |
| T7 | Full repository quality gate and remote synchronization | VERIFIED | Official gate passed; push and clean state recorded below |

## Explicit Supersede contract

- `POST /memory/contexts/{context_id}/supersede` links two existing
  source-qualified canonical Contexts.
- The replacement receives `supersedes_context_id`; the prior Context receives
  `status: superseded` and `superseded_by_context_id`.
- The replacement forward link is written first so the existing reindex repair
  path can reconcile an interrupted backlink update.
- Exact retries are idempotent and do not increment either version again.
- Missing, self-referential, non-canonical, non-Context, or conflicting
  relations are rejected without rewriting Context bodies.
- The MCP tool `alexandria_supersede_context` exposes the same contract.

## Evidence policy

Generated execution data remains isolated from the real user Vault and database.
The latest reproducible collector and sanitized outputs are tracked under
`docs/project_remaining_work/agent-scope-memory-evidence/`. The local
`docs/jobs/version2_alexandria/evidence` directory remains an ignored working
copy according to repository policy.

## Final verification

- Implementation commit: `ca32547`
- Test Run ID: `agent-scope-memory-20260724-ca32547`
- `uv sync`: resolved 111 packages; audited 108 packages
- `uv run ruff format .`: 405 files unchanged
- `uv run ruff check .`: all checks passed
- `uv run pyrefly check`: 0 errors
- `uv run pytest -q`: 535 passed in 20.94s
- Reindex: 4 seen, 4 indexed, 0 skipped, 0 errors
- FTS recall P95: 9.663ms, target <= 500ms
- Hybrid recall P95: 14.456ms, target <= 2000ms
- Context save P95: 21.047ms, target <= 1000ms
- FTS, Vector, and Hybrid boundary result: Agent A plus shared Project only

## Remaining work

No unfinished implementation or verification task remains inside this PRD.
Items explicitly listed as non-goals or deferred scope remain separate work and
are not blockers for this completion decision.
