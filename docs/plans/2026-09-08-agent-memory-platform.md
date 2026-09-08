# Agent Memory Platform implementation

## Latest follow-up verification — 2026-09-09 KST

The subsequent independent skill review found and resolved documentation issues
and two interface defects: verify selector validation now fails at the request
boundary, and managed-spec output failures preserve the existing typed HTTP
mapping. Both independent reviewers accepted the corrections. Final root
`make ci` after these repairs passed: 950 PostgreSQL tests, 34 benchmark tests,
all Python/Rust/mechanical/native gates. See
[the review and exact evidence](agent-memory-platform-evidence/skills-independent-review.md).
The earlier storage receipt below predates this follow-up; no new deployment or
plugin reload was performed.

Publication preparation: the user subsequently authorized Git push. The verified
source/tests are committed as `28629a0`; documentation and skills are packaged
separately. Unrelated local files and the additional `.agents/` ignore entry are
preserved outside these commits. Earlier uncommitted/storage statements below
describe their recorded verification time.

## Initial implementation verification — 2026-09-09 KST

Root `make ci` passed with exit 0 after the final source/schema/durability edits:
945 PostgreSQL tests (88.98 s), 34 benchmark-tool tests, Ruff format/lint,
Pyrefly 0 errors (75 non-error warnings not displayed by the checker), all seven
Python mechanical verifiers, Rust rules/format/check/workspace tests and all
native FFI parity gates. The full log is
[`make-ci-final.log`](agent-memory-platform-evidence/make-ci-final.log), SHA-256
`59d42a8f1359bc94fcf35227054c45f2ada3550acbe4a375bcd94ece1e8c9cda`.

Live storage exposed one final recall defect: non-Context notes without explicit
scope were mapped to PROJECT/GLOBAL when read, but excluded by SQL search. FTS,
vector and graph hydration now use that same existing scope policy. Context notes
without required scope remain excluded; private identities remain fenced. A real
PostgreSQL/Vault regression covers project, global, vector/hybrid and private lanes.
The final aggregate below includes this repair.

The first aggregate run had 928 passes and 6 failures: five cycle test-constructor
integration failures and one alternate-test-app DI binding leak. The bindings
were restored through an explicit test fixture; the final aggregate has no
failures. No timeout increase, test exclusion or production bypass was used.

| Requirement | Final change classification | Delivered boundary |
| --- | --- | --- |
| 01 | extended | AUTO/STRICT high-level recall, exact/title/alias, lexical/semantic cascade, related projects, bounded trace/outcomes; duplicate empty-FTS work removed |
| 02 | extended | Logical verified upsert, CAS/concurrent replay, explicit commit/readback, unknown outcome and corrupt checkpoint refusal |
| 03 | extended | Source-first exact reads and moved-ID recovery, bounded scanning, capability freshness, DB-outage HTTP access, recovery owner fencing |
| 04 | extended | Typed relate, shared Markdown relation mutation, source/edge/backlink/production PostgreSQL-Rust graph convergence |
| 05 | extended | Existing temporal authority reused for current/as-of views, one batch overlay query, future/superseded filtering and conflict preservation |
| 06 | newly implemented composite | Write-free bounded preview, canonical source/target revision fence, exact semantic plan apply, child result replay and one project CURRENT Compact |
| 07 | newly implemented composite | Exact note-ID policy/spec preparation, inert full-hash envelope, caller-output completion and verified replay |
| 08 | extended | Typed MCP/HTTP request/response parity, provenance, structured recovery failures and composite verification with honest unknown projection states |

The six composite MCP tools are registered in the local source server (52 total
tools); all six HTTP composite request bodies are present in OpenAPI. Existing
low-level APIs remain diagnostics/advanced surfaces. Runtime deployments and the
connected plugin were not rebuilt or reloaded as part of these source changes.

### Final simplification and remaining limits

- Reused canonical note/identity, PostgreSQL search/graph, Rust kernels,
  reconciliation plans/results and Memory Compact lifecycle. No new scheduler,
  relationship database, reconciliation engine or idempotency backend was added.
- Report-bundle and relate share one relation mutation owner. Duplicate scans use
  the bounded source inventory. Removed unused parallel managed-spec checkpoint
  codecs; typed checkpoints have an operation-kind envelope and fail closed.
- Source writes and recovery records use file/directory fsync and bounded worker
  I/O. Source durability uncertainty remains UNKNOWN despite successful readback.
- Production/runtime scan found no Neo4j or Librarian references in backend app,
  native crates, Compose or scripts. Historical migrations/logs and negative
  retirement assertions remain intentionally preserved.
- CURRENT Compact is project-scoped. High-level cycles require project scope;
  AGENT/USER/SESSION sources cannot be consolidated into a project CURRENT.
  Workspace-filtered cycles remain draft/review-bound.
- Projection states not actually proven current remain UNKNOWN/PENDING. This
  does not claim synchronous vector/graph completion for every write.
- Fixture embedding evidence proves routing and database/native behavior, not
  universal live semantic quality. New-code deployment and a new release-runtime
  seal remain unexecuted; the final root native gate uses the canonical debug
  extension. Live storage/retrieval follow-through is recorded separately.

Final cycle measurement: 2 candidates used 14/22/4 SQL statements for
preview/apply/replay; 10 candidates used 70/86/12. In the final gate the 10-item
fixture took approximately 182/315/101 ms. Relation fixture: five edges, p50
153.299 ms, sample p95/max 312.616 ms, replay 24.553 ms; graph query count was
not instrumented. See the retained JSON artifacts for sample-specific values.

### Alexandria storage closure

Saved and CAS-updated the implementation Development Log at
`Contexts/Projects/Agent Platform/Development Log/2026/09/Heterarchy Alexandria/10 2026-09-08 Heterarchy Alexandria Agent Memory Platform Implementation and Verification.md`.
Note identity: `6e66ca32-502f-4c69-b82b-fa46aa29251d`, version 3. Exact source
readback matches the submitted final body, and Vault FTS returns the note first.
Full identity/hash and all receipts are in
[`storage-receipt.json`](agent-memory-platform-evidence/storage-receipt.json).

The final reindex indexed 1,898 notes with no errors, and the PostgreSQL/Rust graph
rebuild completed in 0.434367 s. Five existing missing-target relationships remain.
Embedding job `1fddf122cf494c25837849e1150afd91` succeeded, updating four chunks.
At 2026-09-08 15:21:52 UTC the connected service was READY: FTS/vector/embedding
healthy, 22,513 current embedding rows, no missing/stale rows, matching projection
revision, and FTS/VECTOR/HYBRID canaries all passed. This is existing runtime
storage/readiness evidence; the new implementation has not been deployed.

The old live Context search still exhibits the omitted-scope defect; the new SQL
repair is verified by the real PostgreSQL/Vault regression and final aggregate CI.
A current-source live overlay probe was not executed. The old runtime also
redacted the CI hash in an intermediate log revision; the final body references
the repository artifact, which retains the complete hash. Final readback matches.

The user-requested inherited-work checkpoint is `24b91d5`. The implementation
changes after that checkpoint remain uncommitted and have not been pushed.

Baseline: `24b91d579c044ef31d5b533f64cd855dad345c42`. The user requested a
checkpoint of the inherited dirty worktree before implementation. This plan
extends the current PostgreSQL / Markdown / Rust authorities. No retirement
rollback, compatibility shim, new dependency, or domain analysis executor is planned.

## Requirements current-state matrix (before implementation)

The requirements authority is Alexandria index note
`37a69d90-6a0b-4dfe-a752-ec85340598a4`, requirements 01–08 linked from it.
Statuses describe source inspection, not executed acceptance evidence.

| Requirement | Initial status | Existing authority and gap |
| --- | --- | --- |
| 01 Recall | partial | `backend/app/memory/application/contexts/records/context_search_service.py::ContextSearchService` owns FTS/vector/AUTO routing and graph enrichment; `domain/contracts/context_recall_contracts.py::validated_scope_identity` owns strict scope validation. No high-level recall cascade with AUTO identity selection and explicit related-project expansion. |
| 02 Identity / write | partial | `backend/app/obsidian/application/service/notes/obsidian_canonical_identity_service.py::ObsidianCanonicalIdentityService.resolve`, `obsidian_note_service.py::write_note`, and `obsidian_report_bundle_service.py::upsert` own logical report resolution, CAS writes and durable replay. Resolver performs per-note indexed reads; source persistence can succeed before an index exception is returned. Composite verified logical upsert is missing. |
| 03 Degraded / recovery | partial | `obsidian_note_service.py::read_note` / `read_note_by_path` reload Markdown but require metadata rows and trigger reindex on a miss. `backend/app/operations/domain/entities/operational_capability.py::OperationalCapabilitySnapshot` separates core and semantic readiness; `operations/application/recovery/planning/recovery_plan_service.py::RecoveryPlanService` and execution `RecoveryRunService` already own recovery. Raw exact access and per-projection freshness need extension. |
| 04 Graph | partial | Markdown relations, `ObsidianReportBundleService`, PostgreSQL graph projection repository and Rust `graph_compute::read_projection` already exist. Reuse them for an idempotent relate composite and end-to-end hierarchy verification; do not create a second relationship store. |
| 05 Temporal | partial | `backend/app/memory/application/reconciliation/conflicts/memory_temporal_recall_service.py::MemoryTemporalRecallService` and `domain/entities/memory_reconciliation.py::MemoryTemporalState` own validity, supersession and historical recall. `context_temporal_preference.py` currently sorts explicit timestamps; high-level current authority must use temporal eligibility rather than newest-wins. |
| 06 Memory cycle | partial | `MemoryReconciliationPlan`, `MemoryReconciliationResult`, `MemoryConflictSet`, `MemoryCompactFactBuckets`, and reconciliation plan/apply services already exist. A bounded window composite with exact revision fencing and compact convergence remains to be connected. |
| 07 Managed spec | missing | Canonical identity, exact reads and report-bundle persistence are reusable. CodeGraph finds no managed-spec or scheduler service. Need a typed preparation/completion contract that pins policy/spec/output identity while the caller retains domain execution. |
| 08 Provenance / verify | partial | `ContextSearchService.explain_search`, `context_search_trace.py`, retrieval metadata, temporal overlays and existing readiness/recovery diagnostics provide constituent evidence. Compact route outcomes, structured safe next actions and logical-object verify are missing. |

## Bounded implementation and cleanup plan

1. Confirm requirements notes and current entrypoints; record baseline canonical CI.
2. Freeze the recall and exact-read contracts, then implement regression-first
   extensions using existing search and canonical note services.
3. Extend the existing identity/write authority with truthful durable readback,
   retry fencing, projection diagnostics and duplicate-safe logical identity.
4. Connect relation and managed-spec composites to those verified authorities.
5. Complete any temporal/memory-cycle/provenance work started end to end, using
   existing reconciliation plans, conflicts and results.
6. Run a separate touch-path cleanup/review pass. Retired runtime symbols may be
   removed; historical evidence and migration history remain evidence.
7. Measure latency/query counts and payload costs; run focused regressions, then
   the root canonical `make ci` after final edits. Record missing live lanes.
8. Save the implementation Development Log in Alexandria and verify readback.

Main owns architecture, contract freeze, integration and acceptance. Read-only
context/mapping and independent verification run in parallel; bounded writers
receive disjoint ownership. No overlapping source writers are allowed.

## Evidence

- CodeGraph status: 823 files, 13,824 nodes, 37,621 edges; up to date at baseline.
- Baseline canonical CI: `make ci` PASS, exit 0, 103.89 seconds; 842 PostgreSQL
  tests, 34 benchmark-tool tests, Ruff, Pyrefly (0 errors), 7 Python mechanical
  verifiers, Rust/native CI and FFI parity. External log:
  `/tmp/alexandria-memory-platform-baseline-ci.log`, SHA-256
  `b3fa419251934de9f1d3a4c31d8c72d0307e41be69ba757e2539c731af9ec1ed`.
- Requirements completion, performance and live runtime evidence: pending.

## Frozen integration contracts

- Recall AUTO selects only identities actually present; STRICT retains existing
  validation. Related projects are bounded explicit policy input, never a grant
  to read another user's/session's scope. Existing request-scoped SQLAlchemy
  sessions must not be shared concurrently across cascade stages.
- Exact source reads never invoke reindex. A bounded, typed full-source snapshot
  extends existing Vault inventory; incomplete scans cannot prove absence or
  uniqueness. Missing index timestamps remain absent, not invented.
- `ObsidianLogicalIdentity(project, report, date, entity, edition)` is the one
  shared value for the existing logical resolver coordinates.
- Verified upsert serializes resolve/check/write/readback using the existing
  cross-process coordinator. Existing report-bundle checkpoint persistence is
  reused with typed operation records and distinct key namespaces. Replay must
  read back durable source state before mutation; stored source plus failed
  projection is a partial durable result.
  High-level mutation services hold that lease through explicit projection
  commit/readback using request-session commit/rollback callbacks supplied by the
  composition root. Their HTTP handlers use the existing independent-transaction
  marker; middleware must not commit after releasing the source mutation fence.
  Low-level source reads explicitly roll back their projection-only transactions.
- Managed specs use canonical **note IDs**, as required by current Scheduler
  Runtime Policy `5d37e9dd-147a-4dd2-9fc4-2d8fb6287aaa`. The actual Morning Read
  specification is `prompt_evidence_intelligence_morning_read_v3_scheduler_system`.
  Paths/titles and the V6 wrapper with null `execution_spec_note_id` are not
  runtime selectors. Prepare pins exact policy/spec and a reference-only trust
  envelope; completion persists caller-supplied domain output through verified
  upsert. Alexandria does not execute market analysis or arbitrary spec text.
  Conflicting declared workflow/policy authority fails closed. Arbitrary natural
  language intent detection is not claimed as a security boundary.
- Relate persists source frontmatter and its managed Markdown links. It reuses
  the existing canonical mutation, edge indexing, and Rust graph rebuild. Full
  success requires exact relationship evidence, including after replay.
- Memory cycle dry-run performs no source, SQL or checkpoint writes. Its plan
  identity hashes the exact scoped source revisions, current compact revision
  and proposed reconciliation semantics, excluding incidental generated IDs.
  Apply holds the existing writer fence, reconstructs and compares that exact
  semantic plan, then persists the admitted envelope before invoking existing
  child plan/result and compact authorities. Review-required contradictions and
  supersession remain review-bound. SQL, Markdown, compact and graph phases have
  separate evidence; they are not represented as one cross-store transaction.

## Integrated development evidence (not final acceptance)

- Exact-source + search-refresh + request transaction tests: 13 passed using the
  canonical native environment and temporary PostgreSQL script, after initial
  missing-provider integration and native-environment failures were corrected.
  `/tmp/alexandria-exact-source-integrated.log`.
- Subsequent bounded source repairs: 12 source tests, 6 security/search tests and
  8 mapper tests passed in the writer lane; final aggregate rerun is pending.
- Relation regression: 3 passed, including full Harness hierarchy using the
  production PostgreSQL graph repository and Rust native compute; existing report
  bundle regression: 2 passed. Writer evidence awaits independent acceptance.
- Relation performance fixture: 5 directed hierarchy relations, p50 147.218 ms,
  sample p95/max 153.34 ms; replay 22.408 ms. Query count was not instrumented.
  `/tmp/alexandria-relate-performance.json`; no speedup claim.
- MCP construction reports 51 tools with explicit output schemas for the five
  new composites; cycle registration remains pending. This is local source
  registration evidence, not a claim that the connected deployed plugin reloaded.
- Identity resolver comparison used baseline `24b91d5` resolver orchestration and
  current resolver over the same current reader, temporary PostgreSQL, Vault and
  native parser. Five samples after warmup: 10 notes p50 113.429 → 47.243 ms and
  10 → 0 SQL statements; 100 notes p50 1126.146 → 450.169 ms and 100 → 0 SQL
  statements. File parsing remains linear and explicitly bounded; this is not
  a whole-platform or healthy-vector speedup claim.
- Actual cold-start HTTP source reads were tested with an unreachable reserved
  PostgreSQL endpoint. The database resource now constructs the engine while the
  existing lifecycle probe owns availability; metadata-only source-read lookups
  have a one-second budget. Mutation and authentication boundaries still require
  their authoritative dependencies. Final outage test rerun pending after budget
  adjustment.
- Managed-spec output provenance retains full SHA-256 pins. A regression exposed
  long-token redaction of legitimate typed hashes; `sha256:` references now retain
  complete digests while credential fields/assignments still redact. Truncated
  16-character pins were removed. Initial combined security/spec gate: 50 passed;
  final gate includes additional credential-context regressions.

Measured performance artifacts are retained under
[`agent-memory-platform-evidence`](agent-memory-platform-evidence/).

### Measured recall routing optimization

The controlled PostgreSQL/pgvector fixture uses a deterministic test embedding
provider and production native retrieval. It proves routing/cost, not live model
quality. Twenty measured samples per scenario removed repeated lexical retrieval
after an empty FTS result by selecting existing VECTOR_ONLY for that semantic
stage; nonempty low-confidence FTS continues through the existing HYBRID owner.

| Scenario | SQL statements before → after (20 samples) | p50 before → after |
| --- | --- | --- |
| Semantic paraphrase | 180 → 140 | 12.66 → 10.45 ms |
| Related-project expansion | 300 → 220 | 21.78 → 14.26 ms |
| Global exhaustion | 640 → 360 | 73.78 → 24.92 ms |

Vector query counts were unchanged. Current/historical temporal views use one
batch SQL query for three contexts; empty views use none. Measured composite
payloads were 4.25–6.64 KB with median serialization 0.16–0.21 ms. Initial focused
optimization gate: 19 passed; final aggregate and alias regression remain pending.

### Recovery persistence repair

Independent review reproduced competing recovery admissions and foreign owner
checkpoint replacement. The existing active-run record now uses a process-shared
filesystem guard around admission/conditional update/removal; JSON records are
atomically replaced and directory-fsynced. Recovery record effects run on the
bounded framework worker lane. Two failing ownership regressions were added
before repair; focused recovery/admission/router gate then passed 9 tests.
Final aggregate rerun includes the completed serialization policy.

## Live pre-feature performance qualification

The existing deployed runtime is `worktree-105b4601ff55e51998838990`, not a newly
deployed process for baseline commit `24b91d5`. Read-only live benchmarks observed
healthy FTS but embeddings requiring reindex (159 stale and 159 missing rows),
and a projection source revision mismatch. These measurements are degraded
operational baselines, not a controlled healthy before/after comparison.

| Workload | Observed result |
| --- | --- |
| Exact-title, 4 cases x 5 | Recall@3 0.75; case p95 58.677–710.915 ms; FTS_ONLY in all cases |
| Semantic, 10 cases x 5 | Recall@3 0.30; case p95 45.539–926.712 ms; FTS_ONLY in all cases |
| Existing graph AUTO vs HYBRID | Recall@5 0.70 vs 0.15; AUTO p95 408.149 ms; expansion p95 26.985 ms |

Graph ranking parity and complete-path provenance were 1.0, but graph closure
was **not ready** because all 10 cases used a degraded effective strategy.
Reports are `/tmp/alexandria-recall-exact-before.json`,
`/tmp/alexandria-recall-semantic-before.json`, and
`/tmp/alexandria-graph-closure-before.json`.
