---
name: alexandria-current-refresh
description: Draft, semantically edit, review and promote a project CURRENT Memory Compact with exact source/body fences; inspect temporal coverage before daily, weekly or monthly close decisions.
---

# Alexandria CURRENT Refresh

Use for a requested project handoff/CURRENT refresh or period closure. Ordinary
recall stays with [Alexandria Library](../alexandria-library/SKILL.md).

## Establish the source and coverage

Read the current project Compact and the exact supporting sources. Retain source
IDs, detail paths and returned hashes. A source origin type is not its privacy
scope; AGENT/USER/SESSION/WORKSPACE-private observations cannot be exposed through
public project CURRENT. Never invent IDs or echo a requested hash as observed
source evidence.

For date-based closure, read [Temporal coverage](references/temporal-coverage.md).
OPEN days and missing expected sources cannot become a terminal all-clear.

## Draft, edit, review, apply

Preview `alexandria_memory_steward_refresh_current_compact` with `apply=false`
and `draft_only=true`, supplying project-specific `source_refs` and
`semantic_template` or `final_markdown`. The default generated body contains
readiness scaffolding; it is not an inferred project summary. Ground facts in
sources and author the final semantic body before promotion.

If the preview says a refresh is needed, authorized draft creation uses the same
inputs with `apply=true, draft_only=true`. If no refresh is needed, retain the
current result; use `force=true` only for an intentionally requested refresh.
Inspect returned blockers and created Compact identity rather than assuming
`apply=true` always creates a draft. A stale review of the old CURRENT can block
this refresh surface. If the task has configured HTTP access, the existing
`POST /memory/compacts` boundary can create a DRAFT with project, aware
`covered_from`/`covered_to`, `markdown_body`, `status="DRAFT"` and exact
`source_refs`. It does not promote CURRENT. If that boundary is unavailable,
report the draft-creation capability gap; do not rewrite CURRENT directly.

```json
{"tool":"alexandria_memory_steward_refresh_current_compact","arguments":{"project":"heterarchy-alexandria","apply":false,"draft_only":true}}
```

Read the created DRAFT with `alexandria_get_memory_compact`; retain its
`draft_hash`. Edit through the DRAFT-only tool, not an ordinary note-write to a
CURRENT path:

```json
{"tool":"alexandria_edit_memory_compact_draft","arguments":{"compact_id":"returned-draft-id","markdown_body":"Final project-specific Markdown with required headings and linked evidence.","expected_draft_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}
```

The hash above illustrates shape only: use the actual returned `draft_hash`.
Include Durable Decisions, Current State, Risks and Blockers, Next Actions,
Coverage and Evidence Summary. Coverage identifies project and aware start/end
boundaries; Evidence Summary links the actual source IDs/paths/titles.

Call `alexandria_review_memory_compact_draft(compact_id=...)` after the last
semantic edit. General rubric PASS is insufficient: CURRENT admission requires
`total_score == max_score == 20`, available source evidence and no drift. Resolve
missing/unlinked/private references or contradictions and review again.

Authorized promotion uses the exact returned review hash:

```json
{"tool":"alexandria_apply_reviewed_memory_compact","arguments":{"compact_id":"returned-draft-id","expected_review_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}
```

Replace the illustrative hash with the actual `review_hash`. Any body/source
change invalidates it. A body-only edit can reuse unchanged source refs, but the
edit tool cannot replace them. If a pinned source content hash changed, create
a fresh DRAFT with newly observed source refs and review that draft; editing
only the old body cannot cure a stale pinned source hash. A revision-only
change with the same content hash still requires a fresh authoritative review.
Do not reuse old
scores or bypass RAG admission. A failed apply leaves the previous CURRENT in
place. On an uncertain response, read the draft and project CURRENT before
another promotion attempt.

## Verify the final body

Read project CURRENT with `alexandria_get_current_memory_compact(project=...)`.
Require the expected identity, one CURRENT for the project, the final semantic
body, `review_attestation_status="VERIFIED"`, and matching
`reviewed_body_hash`/`current_body_hash` plus the admitted `review_receipt_hash`.
Report operational RAG/graph freshness separately. A local unit/ASGI proof does
not prove a deployed model/provider is healthy.
