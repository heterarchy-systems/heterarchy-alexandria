# heterarchy-alexandria Backend Recall Surface

This document replaces the original backend MVP prompt. The active product is a local-first, agent-facing recall and librarian collaboration service for Hermes/Alexandria. It is not a human CMS, generic archive platform, or SQLite-backed skill/prompt library.

## Current product boundary

heterarchy-alexandria keeps durable knowledge agent-native and Markdown-first:

```text
Hermes/agent/MCP/CLI request
→ Obsidian Markdown capture or backend operational state
→ reindex/search/RAG Context Pack
→ optional librarian collaboration or skill-acquisition job
→ human curation in Obsidian after save
```

Obsidian Markdown is the human-facing source of truth for reusable memory, skills, and prompts. SQLite stores rebuildable indexes/caches plus operational state such as provider profiles, OAuth state, memory compacts, and workflow checkpoints.

## Active backend objects

Active public material is organized around:

- `memory_compact`: durable summaries and project memory exposed through Memory Compact APIs and MCP tools.
- `context` / `context_pack`: recall-oriented Context Vault records and RAG packets; public manual context-write/review routes stay removed.
- `obsidian note`: Markdown-backed memory, skill, and prompt artifacts captured, indexed, searched, read, related, and saved through Obsidian surfaces.
- `librarian profile/provider`: backend-owned routing and credential surfaces for optional delegated librarian work.
- `skill_acquisition_job`: durable operational job for acquiring or drafting a skill artifact from a prompt.
- `obsidian_librarian_workflow`: resumable LangGraph approval workflow checkpoint for Obsidian librarian actions.

Historical SQLite library item kinds such as generic `SKILL`, `PROMPT`, and `HARNESS` item rows were removed from live backend APIs. Keep those names only in migration files, pruning contracts, compatibility notes, or Markdown artifact labels where they describe user-facing content rather than a live SQLite CRUD surface.

## Active backend surfaces

### Obsidian Markdown and Context recall

- capture, save, read, search, reindex, and relate Obsidian notes;
- capture Markdown skill/prompt/memory artifacts through `obsidian capture` and Obsidian plugin flows;
- search/retrieve Context Vault records and build RAG Context Packs;
- prepare and browse Memory Compacts;
- run resumable Obsidian librarian workflows with explicit approval/cancel semantics.

### Librarian collaboration

The librarian is optional collaboration, not the default recall path. Multiple librarian profiles/providers are supported so an operator can route requests to different helper agents or models. Provider credentials remain backend-side; browser/client surfaces must not expose raw secrets.

### MCP and CLI

The MCP server and CLI call the same backend contracts. MCP is the primary agent-facing integration path. CLI commands are useful for local operation, smoke tests, setup, and Obsidian/Memory operations, but they must not reintroduce removed human approval queues or stale CMS-shaped create/review screens.

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
