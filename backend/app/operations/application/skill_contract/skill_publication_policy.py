"""Active Skill admission over registered runtime evidence."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
    update_frontmatter_scalars,
)
from app.operations.domain.entities.skill_contract import SkillRuntimeContract
from app.operations.domain.skill_contract_policy import evaluate_skill_contract
from app.platform.config.app_config import AppConfig
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.types.extra_types import JSONObject, JSONPrimitive


def active_skill_path(path: str) -> bool:
    """Identify the canonical Active Skill folder.

    Args:
        path: Validated managed relative path.

    Returns:
        Whether the path resides in Skills/Active.
    """
    parts = tuple(part.casefold() for part in Path(path).parts)
    return any(
        parts[index : index + 2] == ("skills", "active")
        for index in range(len(parts) - 1)
    )


def skill_body_hash(body: str) -> str:
    """Hash the body excluding canonical serializer wrapper newlines.

    Args:
        body: Submitted or parsed Markdown body.

    Returns:
        Stable body identity preserving all non-wrapper bytes.
    """
    return sha256(body.strip("\n").encode("utf-8")).hexdigest()


class SkillPublicationPolicy:
    """Reject incompatible/unversioned Active publication before source effects."""

    def __init__(self, runtime_provider: Callable[[], SkillRuntimeContract]) -> None:
        """Bind actual runtime evidence.

        Args:
            runtime_provider: Registered manifest and build-owned revisions.
        """
        self._runtime_provider = runtime_provider

    def validate(self, body: str, metadata: JSONObject, *, path: str) -> JSONObject:
        """Admit exact compatible body and create trusted verification fields.

        Args:
            body: Body actually being published.
            metadata: Declared version bounds and manifest pins.
            path: Exact intended Active path.

        Returns:
            Server-owned canonical verification metadata.

        Raises:
            ObsidianValidationError: For incompatible or missing evidence.
        """
        runtime = self._runtime_provider()
        verdict = evaluate_skill_contract(
            body, metadata, runtime, name=Path(path).stem, path=path
        )
        if verdict.status != "COMPATIBLE":
            raise ObsidianValidationError(
                "SKILL_RUNTIME_INCOMPATIBLE: " + "; ".join(verdict.drift_reasons)
            )
        if not runtime.runtime_revision or not runtime.source_repo_revision:
            raise ObsidianValidationError(
                "SKILL_RUNTIME_REVISION_UNVERIFIED: Active publication requires build-owned revisions"
            )
        return {
            "source_repo_revision": runtime.source_repo_revision,
            "skill_contract_version": 1,
            "runtime_contract_min": metadata.get("runtime_contract_min", 1),
            "runtime_contract_max": metadata.get("runtime_contract_max", 1),
            "verified_runtime_revision": runtime.runtime_revision,
            "verified_schema_version": runtime.schema_version,
            "verified_at": datetime.now(UTC).isoformat(),
            "capability_fingerprint": runtime.capability_fingerprint,
            "skill_published_body_hash": skill_body_hash(body),
        }

    def validate_markdown(self, text: str, *, path: str) -> str:
        """Attest Active Skill repairs/moves while preserving exact body bytes.

        Args:
            text: Exact proposed source, not a masked read response.
            path: Intended canonical destination.

        Returns:
            Source with only trusted verification scalars refreshed.
        """
        if not active_skill_path(path):
            return text
        document = parse_markdown_document(text)
        metadata = frontmatter_json(document.frontmatter)
        if metadata.get("alexandria_type") != "skill" or metadata.get(
            "status", "active"
        ) not in {"active", "current"}:
            return text
        metadata.pop("capability_fingerprint", None)
        verified = self.validate(document.body, metadata, path=path)
        verified["skill_source_hash"] = metadata.get(
            "skill_source_hash"
        ) or skill_body_hash(document.body)
        scalars: dict[str, JSONPrimitive] = {}
        for key, value in verified.items():
            if value is None or isinstance(value, str | int | float | bool):
                scalars[key] = value
            else:
                raise ObsidianValidationError("SKILL_VERIFICATION_METADATA_INVALID")
        return update_frontmatter_scalars(text, scalars)


def default_skill_publication_policy(
    runtime_revision: str | None,
) -> SkillPublicationPolicy:
    """Compose lazily from configured build revision and registered toolset.

    Returns:
        Policy that fails closed on unversioned runtimes.
    """
    from app.mcp_server.runtime_tool_catalog import registered_skill_runtime_contract

    return SkillPublicationPolicy(
        lambda: registered_skill_runtime_contract(runtime_revision)
    )


def configured_skill_runtime_provider(
    config: AppConfig,
) -> Callable[[], SkillRuntimeContract]:
    """Bind loaded runtime manifest to the composition root's build configuration.

    Args:
        config: Running application's build-owned configuration.

    Returns:
        Lazy registered-runtime evidence provider.
    """
    from app.mcp_server.runtime_tool_catalog import registered_skill_runtime_contract

    return lambda: registered_skill_runtime_contract(config.runtime_revision)
