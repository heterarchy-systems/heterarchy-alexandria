# Alexandria Operating Loop

Use Alexandria only when it improves grounding or durable capability reuse.

1. Use the current conversation, local files, loaded skills, and relevant project context first.
2. For durable memory gaps, use the current Memory Compact and canonical `alexandria_search` retrieval boundary.
3. For reusable capability gaps, use `alexandria_search` and inspect existing note assets before creating anything.
4. If a matching skill is sufficient, load and use it.
5. If the skill is missing or insufficient, create a bounded Markdown skill/prompt note with `alexandria_create_note` or `alexandria_upsert_note` and preserve evidence refs.
6. Use Alexandria Core MCP tools for search/read/write/graph/curation and Memory Steward tools for reconciliation and compaction.

Never store secrets. Do not invent evidence or activate an insufficiently verified skill.
