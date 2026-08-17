---
title: Verification
status: implemented
created: 2026-05-26
updated: 2026-05-26
owner: heterarchy-alexandria
scope: tests
---

# Verification

Regression test:

```bash
uv run pytest -q tests/obsidian/test_librarian_workflow.py::test_librarian_workflow_applies_approved_graph_links_to_active_note
```

Related suite:

```bash
uv run pytest -q \
  tests/obsidian/test_librarian_workflow.py \
  tests/obsidian/test_graph_relations.py \
  tests/obsidian/test_obsidian_edges.py \
  tests/obsidian/test_obsidian_service.py
```

Expected behavior: approved graph writeback creates an outgoing `cites` edge from
the active note to the librarian source note.
