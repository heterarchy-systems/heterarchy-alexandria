# Use Alexandria Library

When a task references prior work, project decisions, local skills, prompts, or durable context, use Alexandria as an optional local-first library.

Preferred order:
1. Respect `heterarchy-heterarchy-alexandria policy status` and `enabled: false`.
2. Use current conversation, Hermes local memory, loaded skills, and local files first.
3. If durable project memory is needed, read the current Memory Compact before broader recall.
4. Use Context Vault recall/RAG for the specific gap, then library skill/prompt search when capability assets may matter.
5. Use `mcp_alexandria` tools when present.
6. Fall back to `heterarchy-alexandria memory-compacts current`, `heterarchy-alexandria context recall`, `heterarchy-alexandria library`, or HTTP APIs only when needed.
7. Keep librarian delegation optional and tied to explicit user request.

If Alexandria is disabled or unavailable, continue with normal Hermes tools without blocking the user.
