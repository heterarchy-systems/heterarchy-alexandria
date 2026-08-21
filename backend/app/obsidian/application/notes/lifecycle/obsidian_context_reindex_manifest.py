"""Validate Context identity and supersede relations before reindex writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReindexCandidate:
    """One parsed managed note awaiting manifest validation and indexing."""

    path: Path
    payload: ObsidianNoteIndex


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReindexManifestIssue:
    """One candidate rejected by cross-note manifest validation."""

    relative_path: str
    context_id: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReindexManifest:
    """Validated candidates and deterministic per-note rejection details."""

    candidates: tuple[ContextReindexCandidate, ...]
    issues: tuple[ContextReindexManifestIssue, ...]


def validate_context_reindex_manifest(
    candidates: list[ContextReindexCandidate],
) -> ContextReindexManifest:
    """Reject duplicate identities and invalid supersede graphs before writes.

    Args:
        candidates: Parsed notes from one complete vault scan.

    Returns:
        Valid candidates and structured rejection details.
    """
    valid_candidates: list[ContextReindexCandidate] = []
    issues: list[ContextReindexManifestIssue] = []
    note_paths_by_id: dict[str, str] = {}
    context_paths_by_signature: dict[tuple[str | None, ...], str] = {}
    for candidate in candidates:
        payload = candidate.payload
        existing_path = note_paths_by_id.get(payload.note_id)
        if existing_path is not None:
            issues.append(
                _issue(
                    candidate,
                    "DUPLICATE_CONTEXT_ID: "
                    f"{payload.note_id} is also declared by {existing_path}",
                )
            )
            continue
        note_paths_by_id[payload.note_id] = payload.relative_path
        signature = _context_identity_signature(payload)
        if signature is not None:
            duplicate_path = context_paths_by_signature.get(signature)
            if duplicate_path is not None:
                issues.append(
                    _issue(
                        candidate,
                        "DUPLICATE_CONTEXT_CONTENT: canonical scope identity and "
                        f"content hash also belong to {duplicate_path}",
                    )
                )
                continue
            context_paths_by_signature[signature] = payload.relative_path
        valid_candidates.append(candidate)

    context_candidates_by_id = {
        candidate.payload.note_id: candidate
        for candidate in valid_candidates
        if candidate.payload.alexandria_type is AlexandriaNoteType.CONTEXT
    }
    invalid_reasons = _invalid_supersede_reasons(context_candidates_by_id)
    if not invalid_reasons:
        return ContextReindexManifest(
            candidates=tuple(valid_candidates),
            issues=tuple(issues),
        )

    accepted: list[ContextReindexCandidate] = []
    for candidate in valid_candidates:
        reason = invalid_reasons.get(candidate.payload.note_id)
        if reason is None:
            accepted.append(candidate)
            continue
        issues.append(_issue(candidate, f"INVALID_SUPERSEDE: {reason}"))
    return ContextReindexManifest(candidates=tuple(accepted), issues=tuple(issues))


def supersedes_context_id(payload: ObsidianNoteIndex) -> str | None:
    """Return the forward supersede reference for a Context note.

    Args:
        payload: Parsed managed note index payload.

    Returns:
        Superseded Context ID, or None.
    """
    if payload.alexandria_type is not AlexandriaNoteType.CONTEXT:
        return None
    return _json_text(payload.frontmatter, "supersedes_context_id")


def _invalid_supersede_reasons(
    candidates_by_id: dict[str, ContextReindexCandidate],
) -> dict[str, str]:
    invalid_reasons: dict[str, str] = {}
    replacements_by_target: dict[str, str] = {}
    for context_id, candidate in candidates_by_id.items():
        target = supersedes_context_id(candidate.payload)
        if target is not None:
            if target not in candidates_by_id:
                invalid_reasons[context_id] = (
                    f"superseded Context is absent or invalid: {target}"
                )
                continue
            prior_replacement = replacements_by_target.get(target)
            if prior_replacement is not None:
                invalid_reasons[context_id] = (
                    f"Context already has another replacement: {prior_replacement}"
                )
                continue
            target_backlink = _superseded_by_context_id(
                candidates_by_id[target].payload
            )
            if target_backlink not in (None, context_id):
                invalid_reasons[context_id] = (
                    "superseded Context backlink conflicts with replacement: "
                    f"{target_backlink}"
                )
                continue
            replacements_by_target[target] = context_id
        replacement = _superseded_by_context_id(candidate.payload)
        if replacement is None:
            continue
        replacement_candidate = candidates_by_id.get(replacement)
        if replacement_candidate is None:
            invalid_reasons[context_id] = (
                f"replacement Context is absent or invalid: {replacement}"
            )
            continue
        if supersedes_context_id(replacement_candidate.payload) != context_id:
            invalid_reasons[context_id] = (
                "replacement Context does not contain the reciprocal supersedes "
                f"reference: {replacement}"
            )

    for context_id in _cyclic_supersede_ids(candidates_by_id):
        invalid_reasons[context_id] = "supersede relationship contains a cycle"
    _propagate_invalid_targets(candidates_by_id, invalid_reasons)
    return invalid_reasons


def _propagate_invalid_targets(
    candidates_by_id: dict[str, ContextReindexCandidate],
    invalid_reasons: dict[str, str],
) -> None:
    while True:
        newly_invalid: dict[str, str] = {}
        for context_id, candidate in candidates_by_id.items():
            if context_id in invalid_reasons:
                continue
            target = supersedes_context_id(candidate.payload)
            if target is not None and target in invalid_reasons:
                newly_invalid[context_id] = (
                    f"superseded Context is absent or invalid: {target}"
                )
        if not newly_invalid:
            return
        invalid_reasons.update(newly_invalid)


def _context_identity_signature(
    payload: ObsidianNoteIndex,
) -> tuple[str | None, ...] | None:
    if payload.alexandria_type is not AlexandriaNoteType.CONTEXT:
        return None
    frontmatter = payload.frontmatter
    return (
        _json_text(frontmatter, "scope"),
        _json_text(frontmatter, "project"),
        _json_text(frontmatter, "workspace_id"),
        _json_text(frontmatter, "agent_id"),
        _json_text(frontmatter, "user_id"),
        _json_text(frontmatter, "session_id"),
        _json_text(frontmatter, "content_hash"),
    )


def _superseded_by_context_id(payload: ObsidianNoteIndex) -> str | None:
    if payload.alexandria_type is not AlexandriaNoteType.CONTEXT:
        return None
    return _json_text(payload.frontmatter, "superseded_by_context_id")


def _cyclic_supersede_ids(
    candidates_by_id: dict[str, ContextReindexCandidate],
) -> set[str]:
    cyclic_ids: set[str] = set()
    for start_id in candidates_by_id:
        path: list[str] = []
        positions: dict[str, int] = {}
        current_id: str | None = start_id
        while current_id is not None and current_id in candidates_by_id:
            cycle_start = positions.get(current_id)
            if cycle_start is not None:
                cyclic_ids.update(path[cycle_start:])
                break
            if current_id in cyclic_ids:
                break
            positions[current_id] = len(path)
            path.append(current_id)
            current_id = supersedes_context_id(candidates_by_id[current_id].payload)
    return cyclic_ids


def _issue(
    candidate: ContextReindexCandidate,
    message: str,
) -> ContextReindexManifestIssue:
    return ContextReindexManifestIssue(
        relative_path=candidate.payload.relative_path,
        context_id=candidate.payload.note_id,
        message=message,
    )


def _json_text(frontmatter: JSONObject, key: str) -> str | None:
    value = frontmatter.get(key)
    return value if isinstance(value, str) else None
