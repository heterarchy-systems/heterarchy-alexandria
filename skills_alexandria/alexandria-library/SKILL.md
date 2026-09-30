---
name: alexandria-library
description: Retrieve durable project decisions and evidence from Alexandria with bounded briefs, exact source reads and provenance; remember logical outputs or route to focused storage, CURRENT, graph and recovery workflows.
---

# Alexandria Library

Use Alexandria for a durable memory gap after checking the conversation, loaded
skills and relevant local files. Honor an instruction not to use Alexandria.

## Retrieve the specific gap

Reuse a relevant, already-known CURRENT Compact. Otherwise start with
`alexandria_context_brief` using a real project/scope, `byte_budget=16000`,
`record_budget=8`, and `strategy="HYBRID"`. These are starting budgets, not tool
defaults or permission to broaden the user's request.

```json
{"tool":"alexandria_context_brief","arguments":{"query":"What decision governs this project?","project":"heterarchy-alexandria","include_scopes":["PROJECT"],"byte_budget":16000,"record_budget":8,"strategy":"HYBRID","previously_delivered":[]}}
```

Keep delivered `(context_id, content_hash)` pairs in the consumer/session and
send them as `previously_delivered` next time. An updated hash can be delivered
again. Omitted/suppressed references remain exact-refetch candidates; neither
means the source is missing. Read only sources needed for the answer and cite
canonical identities with their current hash/provenance.

Use `alexandria_recall` with `scope_mode="AUTO"` when multi-scope routing or a
remaining gap needs it. Supply available workspace/project/agent/session/user
identities; inspect skipped lanes, effective strategy, trace and nullable
provenance. AUTO can include its declared global fallback. For strict
project-only recall, use `scope_mode="STRICT"`, `project`, and
`include_scopes=["PROJECT"]`; inspect returned scope evidence.

An `exact_selector` has one of `note_id`, `path`, or `logical_identity`. A known
exact source is preferable to repeating broad searches. Degraded retrieval or
an empty result does not prove source loss. Expand the graph only from a seed
that has been read and verified.

## Select the operation

| Need | Procedure |
|---|---|
| Logical project/report/date/entity output | `alexandria_verified_upsert` with a stable key and source CAS on replacement |
| Generic exact-path note, skill or prompt | [Safe Markdown Storage](../safe-markdown-storage/SKILL.md) |
| Project-aware final CURRENT or period coverage | [CURRENT Refresh](../alexandria-current-refresh/SKILL.md) |
| Orphan debt, link evidence or relation suggestions | [Graph Care](../alexandria-graph-care/SKILL.md) |
| Read-only note/identity/projection diagnosis | `alexandria_verify` with exactly one selector |
| Source/index/RAG recovery | [Operational Sync](../operational-sync/SKILL.md) |
| Batch jobs, lost write response or DLQ | [Maintenance and DLQ](../alexandria-maintenance-dlq/SKILL.md) |
| MCP authorization/connection problem | [Connection Hub](../connection-hub/SKILL.md) |

Recall, verified upsert, relate, verify, memory cycle and managed-spec execution
use nested `request` arguments. Context brief and many exact-note/steward tools
use flat arguments. Inspect the deployed registered schema; do not wrap every
tool indiscriminately. Read [Composite examples](references/composite-operations.md)
only when writing logical outputs, applying a memory cycle, or completing a
managed specification.

## Evidence and availability

Source COMMITTED and pending vector/graph projections are separate outcomes.
After a lost response, keep the original request/key and inspect durable
receipts before retry. UNKNOWN or corrupt evidence cannot be cured by a fresh
key or by calling a timeout a failure.

`alexandria_skill_contract_status` compares repo skills, registered schemas and
Active mirrors. Repo edits do not reload a running deployment or publish a Vault
mirror. A missing capability remains an explicit gap; use available exact reads
for diagnosis and continue independent work. Do not recreate missing cycle or
managed-spec mutation APIs with client-side orchestration.

Markdown owns note source/relationships; PostgreSQL owns indexed/runtime
persistence; Rust owns deterministic retrieval/graph compute. Runtime status
comes from current MCP/readiness surfaces. Use only CLI groups shown by the
installed CLI's help.
