"""Guardrails for repository agent rule entrypoints."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CANONICAL_RULE_DIRECTORY = Path(".agents/python_dev_harness/docs/rule")
CANONICAL_RULE_ENTRYPOINTS = (
    CANONICAL_RULE_DIRECTORY / "규칙.md",
    CANONICAL_RULE_DIRECTORY / "README.md",
)
RUST_HARNESS_ROOT = Path(".agents/rust_dev_harness")
RUST_HARNESS_ENTRYPOINTS = (
    RUST_HARNESS_ROOT / "PROJECT_PROFILE.md",
    RUST_HARNESS_ROOT / "README.md",
    RUST_HARNESS_ROOT / "rules/README.md",
    RUST_HARNESS_ROOT / "rules/00-overview.md",
    RUST_HARNESS_ROOT / "rules/01-boundary.md",
    RUST_HARNESS_ROOT / "rules/02-workspace-crate-rules.md",
    RUST_HARNESS_ROOT / "rules/03-typed-domain-rules.md",
    RUST_HARNESS_ROOT / "rules/04-deterministic-compute-rules.md",
    RUST_HARNESS_ROOT / "rules/05-ffi-python-boundary-rules.md",
    RUST_HARNESS_ROOT / "rules/06-error-panic-rules.md",
    RUST_HARNESS_ROOT / "rules/07-testing-verification-rules.md",
    RUST_HARNESS_ROOT / "rules/08-performance-memory-rules.md",
    RUST_HARNESS_ROOT / "rules/09-observability-operations-rules.md",
    RUST_HARNESS_ROOT / "skills/rust-alexandria-compute-engineering/SKILL.md",
)
ENTRYPOINT_DOCUMENTS = (
    Path("AGENTS.md"),
    Path("backend/AGENTS.md"),
    Path("CONTRIBUTING.md"),
    CANONICAL_RULE_DIRECTORY / "15-agent-execution-rules.md",
)
STALE_RULE_PATHS = (
    ".agent/docs/ruls",
    ".agent/docs/rule",
    "backend/.agent/docs/ruls",
    "backend/.agent/docs/rule",
    "backend/.agents/rule",
    "backend/.agents/docs/rule",
    "backend/.agents/python_dev_harness",
    "backend/.agents/rust_dev_harness",
)


def test_canonical_agent_rule_entrypoints_exist() -> None:
    """Ensure the declared canonical rule entrypoints exist."""
    missing = [
        str(path)
        for path in CANONICAL_RULE_ENTRYPOINTS
        if not (REPOSITORY_ROOT / path).is_file()
    ]

    assert missing == []


def test_rust_development_harness_entrypoints_exist() -> None:
    """Ensure the Rust compute harness remains complete before Rust code exists."""
    missing = [
        str(path)
        for path in RUST_HARNESS_ENTRYPOINTS
        if not (REPOSITORY_ROOT / path).is_file()
    ]

    assert missing == []


def test_agent_entrypoint_documents_reference_only_canonical_rule_directory() -> None:
    """Ensure agent entrypoints do not direct agents to stale rule paths."""
    failures: list[str] = []
    canonical_text = str(CANONICAL_RULE_DIRECTORY)

    for relative_path in ENTRYPOINT_DOCUMENTS:
        document = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        if canonical_text not in document:
            failures.append(f"{relative_path}: missing {canonical_text}")
        failures.extend(
            f"{relative_path}: stale {stale_path}"
            for stale_path in STALE_RULE_PATHS
            if stale_path in document
        )

    assert failures == []
