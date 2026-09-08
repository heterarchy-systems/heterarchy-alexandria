# Backend Guidelines

## Scope
Applies to `backend/` and descendants. Root `AGENTS.md` remains repository-wide authority.

## Harness Loading
Before backend changes, load:
1. root `AGENTS.md`;
2. `.agents/python_dev_harness/PROJECT_PROFILE.md` and `HARNESS.toml`;
3. `.agents/python_dev_harness/rules/README.md` plus only task-relevant normal/type/async/Pydantic rules;
4. activated FastAPI / Dependency Injector / MCP v2 profiles and Skills when touched;
5. `.agents/python_rust_dev_harness/` only when the Python↔Rust boundary is touched;
6. relevant source/tests/build evidence.

The retired `.agents/python_dev_harness/docs/rule/` tree is not backend rule authority.

## Backend Architecture
- Pydantic v2 owns external validation/schema boundaries; internal DTOs and typed mappings follow the Python project profile.
- PostgreSQL is runtime persistence and indexed graph-source authority. Redis remains an effect/cache/queue boundary where currently owned.
- Rust owns declared deterministic native compute; Python owns orchestration, policy, lifecycle and persistence/effects.
- No permanent Python fallback for Rust-authoritative compute.
- No SQLite compatibility/fallback runtime.
- Keep dependency-injector composition explicit and lifetimes bounded.

## Change Discipline
Preserve unrelated dirty work. Reuse existing owners before adding new services/config/state/dependencies. Do not use dynamic-attribute builtins (`getattr`, `hasattr`, `setattr`) in production Python. Do not broaden a bounded fix merely because adjacent cleanup is visible.

## Verification
Iterate with the smallest deterministic evidence. Before acceptance run the project/Harness-required broader gates for the touched surface. A check not actually executed is UNVERIFIED, not PASS.

## Parallel Work
Read-only exploration may be parallelized. There is at most one writer for an overlapping file or authority boundary. Main/Coordinator owns final acceptance.
