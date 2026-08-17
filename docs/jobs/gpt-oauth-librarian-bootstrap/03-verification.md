---
title: Verification
status: implemented
created: 2026-05-26
updated: 2026-05-26
owner: heterarchy-alexandria
scope: tests
---

# Verification

## Regression tests

- `tests/librarian/interface/test_hermes_collaboration_router.py`
  - provider/profile name aliases delegate successfully and return canonical IDs.
- `tests/connections/interface/test_librarian_oauth_router.py`
  - OAuth lifecycle accepts provider name aliases.
- `tests/librarian/application/test_agent_service.py`
  - preferred provider assignments accept executable provider names.
- `tests/cli/test_hermes_cli.py`
  - bootstrap command creates missing defaults and can start OAuth with redaction.

## Local smoke

Run after backend install:

```bash
uv run heterarchy-alexandria --json librarian bootstrap-obsidian-oauth \
  --provider-name codex-oauth
```
