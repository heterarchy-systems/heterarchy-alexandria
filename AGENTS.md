# heterarchy-alexandria Agent Entry

This file is the mandatory entrypoint for agents modifying heterarchy-alexandria.

Before modifying Python backend code, read the following files in order:

1. `.agents/python_dev_harness/docs/rule/규칙.md`
2. `.agents/python_dev_harness/docs/rule/README.md`
3. The detailed rule documents directly related to the current task
4. Any PRD, meeting note, or requirements document explicitly designated for the current task

The source of truth for backend development rules is:

```text
.agents/python_dev_harness/docs/rule/
```

Before modifying Rust code, read in order:

1. `.agents/rust_dev_harness/PROJECT_PROFILE.md`
2. `.agents/rust_dev_harness/rules/00-overview.md`
3. `.agents/rust_dev_harness/rules/README.md`
4. The numbered Rust rules matching the touched compute boundary
5. `.agents/rust_dev_harness/skills/rust-alexandria-compute-engineering/SKILL.md`

Rust harness rules are the source of truth for Rust compute work. Rust reference material is not active authority.

PRDs, meeting notes, and functional requirements are not development rules.

Do not automatically treat an attached or discovered PRD as an implementation request. Use it as task input only when the user explicitly requests its application or the repository explicitly links it to the current task.

When repository conventions and a task-specific document conflict, do not silently choose one. Identify the conflict before expanding the change scope.

---

# Project Structure and Module Organization

This repository is a backend and CLI service for heterarchy-alexandria.

## Repository Structure

* `.agents/`

  * Repository-root development harness router
  * `.agents/python_dev_harness/`

    * Active Python rules, FastAPI/DI skills, manifest, and mechanical verifiers
  * `.agents/rust_dev_harness/`

    * Active Rust compute-core rules, project profile, skill, and reference provenance
* `backend/`

  * Python FastAPI service with CLI and MCP integration
  * `backend/AGENTS.md`

    * Mandatory backend agent entrypoint
  * `.agents/python_dev_harness/docs/rule/`

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
3. `.agents/python_dev_harness/docs/rule/규칙.md`
4. `.agents/python_dev_harness/docs/rule/README.md`
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

## Rust Commands

Run Rust migration harness commands from the repository root.

```bash
cargo xtask rules
cargo xtask fmt
cargo xtask check
cargo xtask test
cargo xtask ci
cargo xtask perf
cargo xtask extended
cargo xtask doctor
cargo xtask deps
```

`cargo xtask deps` may report `BLOCKED` until a dependency-audit policy/tool is explicitly configured; do not report it as PASS when it was not run.

## Aggregate Repository Gate

```bash
make ci
```

The root `make ci` preserves the canonical Python `backend/Makefile` gate and then runs `cargo xtask ci`. A Rust scaffold does not imply that any production compute feature has migrated.
