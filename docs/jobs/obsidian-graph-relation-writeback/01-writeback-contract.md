---
title: Writeback Contract
status: implemented
created: 2026-05-26
updated: 2026-05-26
owner: heterarchy-alexandria
scope: graph-relations
---

# Writeback Contract

Approved graph writeback:

1. Requires an active note path.
2. Reads the active note from canonical Markdown.
3. Converts librarian `source_refs` into `source_refs` frontmatter entries.
4. Skips self-links and unsafe/missing paths.
5. Dedupes by `(path, id, relation)`.
6. Re-renders the managed Alexandria links block only.
7. Saves through `ObsidianService.save_note`, preserving the existing note id and
   using the normal temp-file replace and reindex path.

The workflow completion evidence changes from
`add_graph_links:pending-plugin-apply` to `add_graph_links:<active-note-path>`.
