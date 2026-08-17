# heterarchy-alexandria Agent Entry

This file is the mandatory entrypoint for agents modifying the heterarchy-alexandria backend.

Before modifying backend code, read the following files in order:

1. `backend/.agents/docs/rule/규칙.md`
2. `backend/.agents/docs/rule/README.md`
3. The detailed rule documents directly related to the current task
4. Any PRD, meeting note, or requirements document explicitly designated for the current task

The source of truth for backend development rules is:

```text
backend/.agents/docs/rule/
```

PRDs, meeting notes, and functional requirements are not development rules.

Do not automatically treat an attached or discovered PRD as an implementation request. Use it as task input only when the user explicitly requests its application or the repository explicitly links it to the current task.

When repository conventions and a task-specific document conflict, do not silently choose one. Identify the conflict before expanding the change scope.

---

# Project Structure and Module Organization

This repository is a backend and CLI service for heterarchy-alexandria.

## Repository Structure

* `backend/`

  * Python FastAPI service with CLI and MCP integration
  * `backend/AGENTS.md`

    * Mandatory backend agent entrypoint
  * `backend/.agents/docs/rule/`

    * Source of truth for backend development rules
  * `backend/app/`

    * Backend application code
    * Application entrypoint: `backend/app/main.py`
  * `backend/app/platform/`

    * Platform-level concerns such as routing, middleware, lifecycle, configuration, and logging
  * `backend/app/shared/`

    * Definitions and guardrails genuinely reused across multiple concepts
    * Must not become a generic utility bucket
  * `backend/tests/`

    * Backend tests named `test_*.py`
* `docker-compose.yml`

  * Runs the backend service by default
  * Includes an optional `graph` profile for local Neo4j graph read-model projection
* `README.md`

  * High-level setup and startup instructions

The previous Next.js `frontend/` service has been removed.

Do not add npm, Node.js, React, Next.js, or frontend workflows unless the product direction changes explicitly.

Preserve the existing heterarchy-alexandria directory structure unless the current task provides a concrete reason to change it.

Do not create generic modules or directories such as:

* `util`
* `utils`
* `helpers`
* `common`
* `misc`

Prefer purpose-specific names such as:

* `frontmatter_parser.py`
* `scope_identity_validator.py`
* `context_recall_filter.py`
* `compact_promotion_service.py`
* `graph_edge_indexer.py`

---

# Build, Test, and Development Commands

## Required Rule Reading

Before changing backend code, read:

1. `AGENTS.md`
2. `backend/AGENTS.md`
3. `backend/.agents/docs/rule/규칙.md`
4. `backend/.agents/docs/rule/README.md`
5. The detailed rule documents relevant to the current task
6. Task-specific documents explicitly designated by the user or repository

Do not read every detailed rule file automatically when only a subset is relevant.

## Backend Commands

Run backend commands from the `backend/` directory.

```bash
cd backend
uv sync
uv run ruff check .
uv run ruff format .
uv run pyrefly check
uv run pytest -q
```

A backend change is not `VERIFIED` unless the relevant formatting, linting, type checking, and tests have actually completed successfully.

When only part of the verification suite was executed, report:

* The exact commands executed
* Their exit status
* The scope actually verified
* Any checks that were not executed
