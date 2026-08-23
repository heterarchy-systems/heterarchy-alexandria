"""Artifact, evidence, and persisted Markdown validation for acquired skills."""

from __future__ import annotations

from urllib.parse import urlparse

from app.librarian.application.skill_artifacts.skill_artifact_value_policy import (
    _clean_items,
)
from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import RiskLevel
from app.shared.exceptions.librarian_exceptions import LibrarianValidationError
from app.shared.types.extra_types import JSONObject

_REQUIRED_SKILL_SECTIONS: tuple[str, ...] = (
    "## 목적",
    "## 언제 사용해야 하는가",
    "## 언제 사용하지 말아야 하는가",
    "## 입력/사전조건",
    "## 단계별 절차 (Procedure)",
    "## 출력 계약",
    "## 실패 모드와 복구",
    "## 안전·권한·비밀정보 가드레일",
    "## 사용 예시",
    "## Evidence와 claim mapping",
    "## 현재 task에 적용하는 next steps",
    "## 버전/변경 이력",
)


def _validate_artifact(artifact: SkillAcquisitionArtifact) -> None:
    """Validate artifact.

    Args:
        artifact: Artifact used by this operation.
    """
    if not artifact.title.strip():
        raise LibrarianValidationError("Skill artifact title is required")
    if not artifact.purpose.strip():
        raise LibrarianValidationError("Skill artifact purpose is required")
    if not artifact.content.strip():
        raise LibrarianValidationError("Skill artifact procedure content is required")
    evidence = _all_evidence_handles(artifact)
    if (
        artifact.source_summary is not None
        and artifact.source_summary.strip()
        and not evidence
    ):
        raise LibrarianValidationError(
            "Skill artifact source summary requires claim-linked evidence"
        )
    if (
        evidence
        and not (
            artifact.source_summary is not None and artifact.source_summary.strip()
        )
        and not _all_supported_claims(artifact)
    ):
        raise LibrarianValidationError(
            "Skill artifact evidence requires a source summary claim mapping"
        )
    if artifact.evidence_items and not _structured_evidence_complete(artifact):
        raise LibrarianValidationError(
            "Skill artifact evidence items require claim-linked source metadata"
        )
    if artifact.evidence_urls and not (
        artifact.source_summary is not None and artifact.source_summary.strip()
    ):
        raise LibrarianValidationError(
            "Skill artifact evidence requires a source summary claim mapping"
        )
    if artifact.risk_level is RiskLevel.HIGH and len(_evidence_sources(evidence)) < 2:
        raise LibrarianValidationError(
            "High-risk skill artifacts require at least two independent evidence sources"
        )


def _evidence_sources(evidence: list[str]) -> set[str]:
    """Execute evidence sources.

    Args:
        evidence: Evidence used by this operation.

    Returns:
        set[str] result produced by evidence sources.
    """
    sources: set[str] = set()
    for item in evidence:
        parsed = urlparse(item)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            sources.add(parsed.netloc.casefold())
            continue
        sources.add(item.casefold())
    return sources


def _all_evidence_handles(artifact: SkillAcquisitionArtifact) -> list[str]:
    """Execute all evidence handles.

    Args:
        artifact: Artifact used by this operation.

    Returns:
        list[str] result produced by all evidence handles.
    """
    handles = _clean_items(artifact.evidence_urls)
    handles.extend(
        item.url_or_path.strip()
        for item in artifact.evidence_items
        if item.url_or_path.strip()
    )
    return handles


def _structured_evidence_complete(artifact: SkillAcquisitionArtifact) -> bool:
    """Execute structured evidence complete.

    Args:
        artifact: Artifact used by this operation.

    Returns:
        Whether structured evidence complete.
    """
    for item in artifact.evidence_items:
        if not item.url_or_path.strip():
            return False
        if not _clean_items(item.supports_claims):
            return False
    return True


def _all_supported_claims(artifact: SkillAcquisitionArtifact) -> list[str]:
    """Execute all supported claims.

    Args:
        artifact: Artifact used by this operation.

    Returns:
        list[str] result produced by all supported claims.
    """
    claims: list[str] = []
    for item in artifact.evidence_items:
        claims.extend(_clean_items(item.supports_claims))
    return claims


def _verify_saved_contract(
    saved_body: str,
    saved_frontmatter: JSONObject,
    expected_body: str,
    expected_frontmatter: JSONObject,
) -> None:
    """Verify saved contract.

    Args:
        saved_body: Saved body used by this operation.
        saved_frontmatter: Saved frontmatter used by this operation.
        expected_body: Expected body used for validation.
        expected_frontmatter: Expected frontmatter used for validation.
    """
    if saved_body.strip() != expected_body.strip():
        raise LibrarianValidationError("Published skill artifact body read-back failed")
    missing_sections = [
        section for section in _REQUIRED_SKILL_SECTIONS if section not in saved_body
    ]
    if missing_sections:
        raise LibrarianValidationError(
            "Published skill artifact missing required sections: "
            + ", ".join(missing_sections)
        )
    required_frontmatter = (
        "version",
        "purpose",
        "when_to_use",
        "when_not_to_use",
        "required_tools",
        "risk_level",
        "created_by",
        "source_job_id",
        "source_prompt_id",
        "evidence_urls",
        "evidence_items",
        "source_summary",
        "created_at",
        "reviewed_at",
        "supersedes",
    )
    missing_frontmatter = [
        key for key in required_frontmatter if key not in saved_frontmatter
    ]
    if missing_frontmatter:
        raise LibrarianValidationError(
            "Published skill artifact missing required frontmatter: "
            + ", ".join(missing_frontmatter)
        )
    for key in required_frontmatter:
        if saved_frontmatter[key] != expected_frontmatter[key]:
            raise LibrarianValidationError(
                f"Published skill artifact frontmatter mismatch: {key}"
            )
