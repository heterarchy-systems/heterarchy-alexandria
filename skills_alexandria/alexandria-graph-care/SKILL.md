---
name: alexandria-graph-care
description: Diagnose Alexandria graph link issues and orphan debt, inspect evidence-backed relation candidates, and record standalone decisions or verify resolution without automatically creating links or targets.
---

# Alexandria Graph Care

Use when graph discovery, missing parents, orphan debt or a particular relation
needs inspection. Normal memory delivery uses the Library brief first.

Markdown owns durable relationships, PostgreSQL owns indexed graph state, and
Rust computes graph projection/traversal/suggestions. Do not add another graph
store or reproduce graph compute in client-side Python.

## Identify the kind of debt

Read `alexandria_get_graph_projection_status` and, for missing/ambiguous links,
`alexandria_graph_list_issues`. Projection `status=ready` and link `issue_total=0`
do not prove orphan debt is zero. If projection is uninitialized/unavailable,
repair it through [Operational Sync](../operational-sync/SKILL.md) before making
a resolution claim.

```json
{"tool":"alexandria_list_graph_orphans","arguments":{"request":{"project":"heterarchy-alexandria","limit":50}}}
```

Page using the returned `next_cursor`, preserving the same project/filter.
Maximum census page size is 200. The census records first/last-seen diagnostic
metadata; it does not create or edit canonical notes. Distinguish measured
`debt_kinds`, in/out degree, `canonical_parent_count`, wikilink-only connectivity
and declared unresolved relations. A wikilink is not canonical contains-parent
ownership. Archive/historical standalone notes can be intentional.

## Read suggestions as evidence

Read one exact seed note before requesting candidates:

```json
{"tool":"alexandria_suggest_graph_relations","arguments":{"request":{"note_id":"exact-existing-note-id","limit":10}}}
```

Use a note ID or canonical path; maximum 50 suggestions. Inspect candidate
identity/path, proposed relation, shared tags/neighbors, title overlap,
confidence and explanation. Read the exact candidate before treating it as a
parent. No returned suggestion grants permission to mutate a relation. Do not
create a target merely to make the orphan count zero.

If a relationship repair is requested and evidence supports it, use
`alexandria_relate` with nested request fields `source_note_id`,
`target_note_id`, `relation`, a stable `idempotency_key`, and the returned source
hash as `expected_source_hash`. For canonical parent ownership, the source is
the existing parent/hub and the target is the child with relation `contains`.
Keep source/edge/backlink/projection evidence separate; resolve uncertain
outcomes through receipts before retry.

## Record intentional standalone or verify resolution

When the task calls for accepting a standalone node:

```json
{"tool":"alexandria_acknowledge_graph_orphan","arguments":{"request":{"note_id":"exact-existing-note-id","decision":"ACKNOWLEDGED_STANDALONE","reason":"Intentional archived reference; no canonical parent required.","acknowledged_by":"task-operator"}}}
```

`IGNORED_WITH_REASON` requires a reason. Acknowledgement is persisted provenance,
not debt deletion. An existing different decision is a conflict.

After an authorized repair and current projection verification, use:

```json
{"tool":"alexandria_get_graph_orphan_status","arguments":{"request":{"note_id":"exact-existing-note-id"}}}
```

OPEN/acknowledged statuses describe current debt. RESOLVED requires a verified,
initialized projection with the actual node and no current native debt; a
missing node/projection cannot prove resolution. Retain first/last run IDs and
readback evidence. A reappearing debt preserves acknowledgement history.
