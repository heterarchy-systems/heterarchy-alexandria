# Use Alexandria Library

When a task references prior work, project decisions, local skills, prompts, or durable context, use Alexandria as an optional local-first library.

Preferred order:
1. Respect an explicit user/session instruction not to use Alexandria; do not invoke nonexistent legacy `policy` or `doctor` CLI commands.
2. Use current conversation, Hermes local memory, loaded skills, and local files first.
3. Reuse an already-known current Memory Compact when relevant; otherwise recall the specific gap without a mandatory preliminary lookup.
4. Use `alexandria_recall` for the specific gap, retaining its route, scope and source/projection evidence.
5. Prefer `alexandria_verified_upsert`, `alexandria_relate`, `alexandria_verify`, and the exact-plan `alexandria_memory_cycle` composite when present. Use managed-spec preparation/completion for scheduler specification and output persistence; keep domain work with the caller.
6. These composite tools take `request={...}`. Inspect registered schemas and capability availability; repository edits do not reload the service. If missing, report the gap and use available exact reads or scoped searches for diagnosis, without inventing a replacement mutation loop.
7. For generic skills/prompts without report/date/entity identity, use the exact note-write API with read-modify-write CAS. Follow [Safe Markdown Storage](../safe-markdown-storage/SKILL.md) for this boundary.
8. Invoke [Operational Sync](../operational-sync/SKILL.md) only for indicated projection repair. A stored source with pending projections remains stored; do not recreate it or change the idempotency key after an unknown outcome.

If Alexandria is disabled or unavailable, continue independent work with available
context and state the memory-dependent gap. Do not claim unavailable memory was
searched, written or verified.
