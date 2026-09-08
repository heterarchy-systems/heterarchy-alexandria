# Neo4j and Librarian retirement closure

Preserve the inherited dirty worktree. PostgreSQL owns durable graph source/read
state; Rust owns deterministic compute; Python owns lifecycle and effects. Retired
product authority is deleted; historical migrations and negative guards remain.

## Bounded cleanup and verification plan

1. Restore Ruff formatting and measure collection before changing behavior.
2. Resolve observed filesystem import stalls in the development environment.
   Baseline: 0 collected after 195.04 seconds, interrupted while reading files.
   Both `.venv` dependencies and source `__pycache__` contain dataless files.
   External environment plus bytecode cache: 677 collected with 23 existing
   collection errors in 6.54 seconds. This is not a passing suite.
3. Correct stale PostgreSQL-only fixtures and preserve test isolation. Measure
   execution and cleanup overhead before choosing any cleanup optimization.
4. Remove observed native provider import-time construction, with regression
   coverage proving import performs no native load and compute still fails closed.
   Retain Rust-only computation; introduce no Python fallback.
5. Use CodeGraph and independent read-only retirement audit to select remaining
   directly connected dead authority/config/tests/docs. Main freezes each repair;
   implementation ownership does not overlap independent verification.
6. Run focused tests, Ruff, Pyrefly, benchmarks, mechanical checks, and root
   `make ci` after final edits. Fix actual failures without weakening contracts.
7. Rebuild/recreate authorized local runtime; verify 46 MCP registrations, retired
   tool/type absence, PostgreSQL graph authority, Memory Steward, and provenance.
8. Record exact evidence, remaining risks, and any unverified lanes.

CodeGraph initialized with 820 files, 13,757 nodes and 37,484 edges. Initial 187
read errors concern deleted tracked paths; verify live coverage separately.

## Verified closure — 2026-09-08

The inherited retirement changes and the follow-up repairs are verified in source,
canonical CI, the rebuilt local containers, and live MCP/backend calls. No commit
or push was performed. The pre-existing dirty worktree was preserved.

### Meaningful repairs

- Removed the unused LangGraph dependency closure and stale current Librarian
  guides/skills. Historical migrations and negative retirement tests remain.
- Removed graph `disabled` rebuild/status/schema branches; production composition
  requires the PostgreSQL graph repository. Updated stale test expectations.
- Moved note-index native adapter construction out of module import and into note
  indexing. A subprocess regression proves app import does not load native compute
  and actual indexing still fails closed without it.
- Replaced inherited Python one-hop scoring, selection, ordering and evidence
  classification with Rust `graph_compute::read_projection`. Python only maps the
  typed native wire. Core/wire/integration tests cover preserved behavior. The
  `contains` weight remains the previous production Cypher default `0.4`; the test
  fake's inconsistent `0.6` was corrected rather than changing production behavior.
- Reused one session-owned cleanup loop and bounded connection while retaining
  full per-test `TRUNCATE ... RESTART IDENTITY CASCADE` and Alembic state.
- Fixed the generated Python Harness manifest's retired source roots, the Rust
  rules router, and child Clippy toolchain selection. MSRV remains Rust 1.98.
- Created and synchronized CodeGraph; used role-specific Luna subagents for
  exploration, implementation and independent review. Main retained authority
  decisions and final integration.

### Performance evidence

| Measurement | Before | Final |
| --- | ---: | ---: |
| Collection | 0 tests after 195.04 s; interrupted | 842 tests in 1.75 s |
| Per-test DB cleanup aggregate | 36.42 s / 842 tests | 13.95 s / 842 tests |
| Whole pytest elapsed | 85.49 s | 67.76 s |

The baseline suite had 16 failures; the final suite has none. These are measured
wall times, not a controlled kernel benchmark. A fixture-only intermediate run
took 60.53 s, with 11.43 s of cleanup. Final timings include the Rust graph cutover.
The original 352.76 s interruption was supplied in the handoff, not rerun here.

The major collection cause was macOS dataless dependency and bytecode files:
the OS sample was blocked in `read`, and small AnyIO imports took 1.6–8.3 seconds.
The fresh environment and bytecode cache live outside the synced checkout. The old
environment is preserved at `backend/.venv.dataless-preserved-20260908`; `.venv`
links to `/Users/imhaneul/.cache/heterarchy-alexandria/venv`. Canonical Make/test
entrypoints set an external bytecode cache while preserving explicit overrides.

### Executed gates

- Root `make ci`: PASS after final production/test/toolchain changes.
- Ruff format/check and Pyrefly: PASS, 0 type errors.
- PostgreSQL pytest: 842 passed; benchmark-tools pytest: 34 passed.
- Python mechanical Harness: 7 enabled verifiers PASS.
- Rust rules, format, check/Clippy, workspace tests and native FFI parity: PASS.
- Independent import/lifecycle review: PASS; self-contained import smoke passed
  in 4.07 s in the independent run.
- Scoped documentation links/fences and `git diff --check`: PASS.

### Runtime and data evidence

Runtime, expected and native revision all equal
`worktree-105b4601ff55e51998838990`; native build profile is `release` and drift is
false. Backend and maintenance worker were rebuilt/recreated. Compose also
reconciled its Redis dependency. PostgreSQL data was retained.

- Removed the old `alexandria-graph` container. No Neo4j service remains running.
  Old offline Neo4j volumes were not deleted.
- Alembic head is `202609071940_librarian_drop`; all five retired Librarian tables
  are absent. They were empty before migration. Canonical note/chunk/reconciliation
  tables were retained.
- Encrypted PostgreSQL backup and isolated restore drill: VERIFIED, including
  revision/table-count/vector checks and removal of the drill's temporary DB.
- Three historical Markdown notes had retired `librarian_brief` metadata. Their
  type was normalized to `implementation_history`; IDs, paths, statuses and body
  bytes were preserved, with original-file backups and hash evidence.
- Vault reindex: 1,969 files seen; 1,887 indexed; 82 unmanaged files skipped;
  stale 0; errors 0. PostgreSQL/Rust graph: 1,887 nodes and 6,463 edges, ready.
- Live MCP stdio protocol in the deployed container: exactly 46 tools, exact
  source-registration match, retired tools absent, create-note Librarian types
  absent. Graph and Memory Steward tools called the live HTTP backend successfully.
- The existing authenticated Alexandria connector independently returned
  PostgreSQL graph status and related-note results, operational `READY`, and
  Memory Steward `ready=true`.
- Queued embedding job `29fbbfa39d0541629785de1b7078e2fe`: SUCCEEDED on attempt 1;
  992 scanned/updated, no warnings. All 22,343 eligible embeddings are current;
  missing/stale 0. FTS, vector and hybrid canaries passed.
- Operational warnings, blockers and next actions are empty. Projection integrity
  is healthy, and source/current revisions match. Queue pending count is 0.

Two pre-existing nonblocking diagnostics are intentionally retained: five graph
edges with missing targets, and one dead-letter record from 2026-09-04 describing
an index-maintenance lease conflict. They were not erased to manufacture a clean
report. No broader corpus quality or extended performance claim is made from the
readiness canaries.

### Evidence and recovery locations

Executed logs, the reproducible live MCP probe, performance measurements, live
responses, note-normalization hashes and restore-drill result are in
[retirement-closure-evidence](retirement-closure-evidence/).

Encrypted backup: `backups/postgres/20260908T075634Z-77389/`.
The locally generated backup key is in the mode-0600 file
`/Users/imhaneul/.cache/heterarchy-alexandria/retirement-backup-key-20260908`.
Historical Markdown originals are under
`/Users/imhaneul/.cache/heterarchy-alexandria/retired-note-frontmatter-20260908/`.
No secret values are stored in this report or the tracked evidence.
