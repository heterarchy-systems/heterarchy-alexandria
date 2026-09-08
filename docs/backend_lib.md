# heterarchy-alexandria Backend Recall Surface

This document replaces the original backend MVP prompt. The active product is a local-first, agent-facing recall and Memory Steward service for Hermes/Alexandria. It is not a human CMS, generic archive platform, or SQLite-backed skill/prompt library.

## Current product boundary

heterarchy-alexandria keeps durable knowledge agent-native and Markdown-first:

```text
Hermes/agent/MCP request
→ Obsidian Markdown note or backend operational state
→ PostgreSQL reindex/search/RAG Context Pack
→ Memory Steward compact/reconciliation lifecycle
→ human curation in Obsidian after save
```

Obsidian Markdown is the human-facing source of truth for reusable memory, skills, and prompts. PostgreSQL stores durable indexed source and operational state; Redis owns the bounded maintenance queue. Rust owns deterministic graph projection, traversal, and candidate selection.

## Active backend objects

Active public material is organized around:

- `memory_compact`: durable summaries and project memory exposed through Memory Compact APIs and MCP tools.
- `context` / `context_pack`: recall-oriented Context Vault records and RAG packets; public manual context-write/review routes stay removed.
- `obsidian note`: Markdown-backed memory, skill, and prompt artifacts created, indexed, searched, read, related, and moved through Obsidian HTTP/MCP surfaces.
- `graph projection`: PostgreSQL-sourced, Rust-computed rebuildable graph read model.
- `memory_steward`: readiness, CURRENT compact refresh, reconciliation, and review lifecycle.

Historical SQLite library item kinds such as generic `SKILL`, `PROMPT`, and `HARNESS` item rows were removed from live backend APIs. Keep those names only in migration files, pruning contracts, compatibility notes, or Markdown artifact labels where they describe user-facing content rather than a live SQLite CRUD surface.

## Active backend surfaces

### Obsidian Markdown and Context recall

- capture, save, read, search, reindex, and relate Obsidian notes;
- create/update Markdown skill/prompt/memory artifacts through the registered MCP note tools;
- search/retrieve Context Vault records and build RAG Context Packs;
- prepare and browse Memory Compacts;
- run bounded Memory Steward compact and reconciliation workflows with explicit readiness checks.

### Memory Steward

Memory Steward owns CURRENT Memory Compact freshness, reconciliation planning,
conflict review, and bounded apply operations. It is separate from Context
Vault retrieval and does not delegate ordinary recall to a provider.

### MCP and CLI

The MCP server and CLI call the same backend contracts. MCP is the primary
agent-facing integration path. CLI commands are limited to MCP serving/smoke
checks and Memory Steward readiness/refresh/preflight/check operations; they
must not reintroduce stale CMS-shaped create/review screens.

## Removed or non-core surfaces

The following are not active core product surfaces:

- Next.js/frontend runtime;
- SQLite library item CRUD and category/folder management;
- SQLite-backed skill/prompt/harness CRUD;
- Capture Review pre-save screen;
- human approval queue for agent-submitted candidates;
- generic object-storage/MinIO import bridge;
- direct human authoring pages for skills/prompts/context;
- public Context Vault lint/manual-save routes.

If one of these capabilities becomes necessary again, design it as a dedicated Obsidian/importer/agent-owned capture path with its own contract and migration story instead of reusing historical draft text.

## Verification guidance

When pruning or restoring a backend surface:

1. Add or update a negative contract test first.
2. Confirm the test fails for the stale surface.
3. Remove route/schema/service/docs exposure.
4. Run focused contracts, then the GitHub Actions parity pre-push hook.
5. Leave historical references only in migration files, pruning contracts, or dated implementation notes where they explain compatibility.
