"""Parity tests between the Rust compile plan and legacy change detectors."""

from __future__ import annotations

import pytest

from app.shared.infrastructure.native_compile_plan import (
    COMPILE_PLAN_CONTRACT_VERSION,
    create_native_compile_plan_provider,
)

_POLICY_KEY = "embed-v1"


def _policy(fingerprint_key: str = _POLICY_KEY) -> dict:
    """Build one compile policy payload."""
    return {
        "chunk_max_chars": 600,
        "chunk_overlap_chars": 80,
        "embedding_fingerprint_key": fingerprint_key,
    }


def _document(relative_path: str, body: str, frontmatter: dict) -> dict:
    """Build one analyzed current document wire payload."""
    return {
        "relative_path": relative_path,
        "note_id": f"note-{relative_path}",
        "title": "Sample Note",
        "alexandria_type": "job_plan",
        "status": "active",
        "aliases": [],
        "text": f"---\n---\n\n{body}",
        "source_hash": "",
        "body": body,
        "frontmatter": frontmatter,
        "edge_seeds": [],
        "provided_chunks": None,
        "provided_edges": None,
        "manifest_candidate": None,
    }


def _previous_document(relative_path: str, source_hash: str) -> dict:
    """Build one previous compiled state payload."""
    return {
        "note_id": f"note-{relative_path}",
        "relative_path": relative_path,
        "source_hash": source_hash,
        "chunk_hashes": [source_hash],
        "edge_ids": [],
    }


def _legacy_decisions(
    current: dict[str, str],
    previous: dict[str, str],
    *,
    fingerprint_stale: bool,
) -> dict[str, set[str]]:
    """Reproduce the legacy set-difference detector decisions for comparison.

    Args:
        current: Mapping of path to current source hash.
        previous: Mapping of path to previous source hash.
        fingerprint_stale: Whether the embedding freshness key changed.

    Returns:
        Changed, added, removed, and re-embed path sets.
    """
    changed = {
        path
        for path, source_hash in current.items()
        if path not in previous or previous[path] != source_hash
    }
    added = {path for path in changed if path not in previous}
    removed = set(previous) - set(current)
    reembed = changed | (set(previous) if fingerprint_stale else set())
    return {"changed": changed, "added": added, "removed": removed, "reembed": reembed}


@pytest.fixture(name="provider")
def provider_fixture() -> object:
    """Create the native compile-plan provider."""
    return create_native_compile_plan_provider()


def test_compile_plan_matches_legacy_change_detectors(provider: object) -> None:
    """The plan must reproduce the legacy detector decisions on one corpus."""
    previous_state = {
        "Contexts/unchanged.md": "hash-unchanged",
        "Contexts/changed.md": "hash-old",
        "Contexts/removed.md": "hash-removed",
    }
    current_state = {
        "Contexts/unchanged.md": "hash-unchanged",
        "Contexts/changed.md": "hash-new",
        "Contexts/added.md": "hash-added",
    }
    current_documents = [
        _document(path, f"body of {path}", {"id": f"note-{path}"})
        for path in sorted(current_state)
    ]
    previous = {
        "embedding_fingerprint_key": _POLICY_KEY,
        "documents": [
            _previous_document(path, source_hash)
            for path, source_hash in sorted(previous_state.items())
        ],
    }
    source_hashes = dict(current_state)

    plan = provider.compile(  # type: ignore[attr-defined]
        policy=_policy(),
        current_documents=current_documents,
        previous=previous,
    )
    assert plan["contract_version"] == COMPILE_PLAN_CONTRACT_VERSION

    # Rust computes the authoritative source hashes from the submitted text.
    for upsert in plan["upserts"]:
        source_hashes[upsert["relative_path"]] = upsert["source_hash"]
    previous_hashes = dict(previous_state)
    legacy = _legacy_decisions(
        source_hashes,
        previous_hashes,
        fingerprint_stale=False,
    )

    upsert_paths = {upsert["relative_path"] for upsert in plan["upserts"]}
    removal_paths = {removal["relative_path"] for removal in plan["removals"]}
    reembed_paths = {
        upsert["relative_path"]
        for upsert in plan["upserts"]
        if upsert["embedding"]["action"] == "REEMBED"
    }

    assert upsert_paths == legacy["changed"]
    assert removal_paths == legacy["removed"]
    assert reembed_paths == legacy["reembed"] - {
        path for path in upsert_paths if plan_upsert_is_metadata_only(plan, path)
    }


def plan_upsert_is_metadata_only(plan: dict, relative_path: str) -> bool:
    """Return whether one upsert carries no embedding work.

    Args:
        plan: Decoded compile plan.
        relative_path: Upsert path to inspect.

    Returns:
        True when the upsert re-embeds nothing.
    """
    for upsert in plan["upserts"]:
        if upsert["relative_path"] == relative_path:
            return upsert["embedding"]["action"] == "NONE"
    return False


def test_compile_plan_is_deterministic_across_repeated_calls(
    provider: object,
) -> None:
    """Same snapshots and policy must compile to the identical plan."""
    current_documents = [
        _document("Contexts/determinism.md", "stable body", {"id": "note-x"})
    ]
    previous = {
        "embedding_fingerprint_key": _POLICY_KEY,
        "documents": [],
    }
    first = provider.compile(  # type: ignore[attr-defined]
        policy=_policy(),
        current_documents=current_documents,
        previous=previous,
    )
    second = provider.compile(  # type: ignore[attr-defined]
        policy=_policy(),
        current_documents=current_documents,
        previous=previous,
    )
    assert first == second
    assert first["plan_fingerprint"] == second["plan_fingerprint"]


def test_compile_plan_is_noop_with_complete_previous_state(provider: object) -> None:
    """A persisted source/chunk/edge snapshot must make unchanged input a no-op."""
    current_documents = [
        _document("Contexts/noop.md", "stable body", {"id": "note-noop"})
    ]
    first = provider.compile(  # type: ignore[attr-defined]
        policy=_policy(),
        current_documents=current_documents,
        previous={"embedding_fingerprint_key": _POLICY_KEY, "documents": []},
    )
    assert len(first["upserts"]) == 1
    upsert = first["upserts"][0]
    previous = {
        "embedding_fingerprint_key": _POLICY_KEY,
        "documents": [
            {
                "note_id": upsert["note_id"],
                "relative_path": upsert["relative_path"],
                "source_hash": upsert["source_hash"],
                "chunk_hashes": [chunk["content_hash"] for chunk in upsert["chunks"]],
                "edge_ids": [edge["edge_id"] for edge in upsert["edges"]],
            }
        ],
    }

    second = provider.compile(  # type: ignore[attr-defined]
        policy=_policy(),
        current_documents=current_documents,
        previous=previous,
    )

    assert second["upserts"] == []
    assert second["removals"] == []


def test_compile_plan_reembeds_unchanged_document_when_fingerprint_changes(
    provider: object,
) -> None:
    """Embedding generation changes must not be hidden by an unchanged source."""
    current_documents = [
        _document("Contexts/embedding.md", "stable body", {"id": "note-embedding"})
    ]
    first = provider.compile(  # type: ignore[attr-defined]
        policy=_policy("embed-v1"),
        current_documents=current_documents,
        previous={"embedding_fingerprint_key": "embed-v1", "documents": []},
    )
    upsert = first["upserts"][0]
    previous = {
        "embedding_fingerprint_key": "embed-v1",
        "documents": [
            {
                "note_id": upsert["note_id"],
                "relative_path": upsert["relative_path"],
                "source_hash": upsert["source_hash"],
                "chunk_hashes": [chunk["content_hash"] for chunk in upsert["chunks"]],
                "edge_ids": [edge["edge_id"] for edge in upsert["edges"]],
            }
        ],
    }

    second = provider.compile(  # type: ignore[attr-defined]
        policy=_policy("embed-v2"),
        current_documents=current_documents,
        previous=previous,
    )

    assert len(second["upserts"]) == 1
    assert second["upserts"][0]["action"] == "EMBEDDING_ONLY"
    assert second["upserts"][0]["embedding"]["action"] == "REEMBED"
    assert second["removals"] == []
