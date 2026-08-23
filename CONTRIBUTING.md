# Contributing

This repository currently ships the heterarchy-alexandria backend, CLI, and MCP integration only. The old frontend package has been removed.

## Backend workflow

```bash
cd backend
uv sync
uv run ruff format .
uv run ruff check .
uv run pyrefly check
uv run pytest -q
```

Before backend changes, read `backend/AGENTS.md` and the canonical development rules under `.agents/python_dev_harness/docs/rule/`.

## Pull requests

Include:
- summary and impacted areas
- validation commands/results
- risk and rollback notes for config, lifecycle, storage, or logging changes

Do not add package-manager installs or frontend dependencies unless maintainers explicitly restore a frontend direction.
