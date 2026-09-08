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
from Git, including repository history. Keep its local agent rules, skills, and
documents in place and do not publish them. They guide agent development; they
are not a prerequisite for running CI.

Run `make ci` from the repository root for the Python and Rust quality gate.
A plain checkout can run this gate without `.agents/`. The executable Python
contract checks and their configuration are tracked in
`backend/scripts/verification/`; Rust checks are tracked in `native/xtask/`.
These checks remain mandatory. Private bundle-presence and manifest checks
belong to local Harness maintenance, not repository CI.

## Pull requests

Include:
- summary and impacted areas
- validation commands/results
- risk and rollback notes for config, lifecycle, storage, or logging changes

Do not add package-manager installs or frontend dependencies unless maintainers explicitly restore a frontend direction.
