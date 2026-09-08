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

Before backend changes, read `backend/AGENTS.md` and the canonical development
rules under `.agents/python_dev_harness/rules/`.

The Engineering Harness under `.agents/` is private and intentionally excluded
from Git, including repository history. Obtain the authorized private bundle and
place it at `.agents/` before running the canonical root `make ci`. Keep the local
bundle in place; do not commit it or copy its contents into public artifacts.
CI runners also require private provisioning before `make ci`; a plain checkout
does not contain the bundle. Missing provisioning is a blocked prerequisite, not
permission to skip the Harness checks.

## Pull requests

Include:
- summary and impacted areas
- validation commands/results
- risk and rollback notes for config, lifecycle, storage, or logging changes

Do not add package-manager installs or frontend dependencies unless maintainers explicitly restore a frontend direction.
