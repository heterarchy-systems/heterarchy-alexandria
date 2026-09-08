"""Exact path and metadata-backed canonical report identity resolution."""

from __future__ import annotations

from datetime import date as calendar_date

from app.obsidian.application.notes.lifecycle.obsidian_canonical_note_path import (
    canonical_managed_note_path,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianCanonicalIdentityResult,
    ObsidianExactPathStatus,
    ObsidianNote,
    ObsidianVaultSourceSnapshot,
)
from app.obsidian.infrastructure.markdown.paths import safe_filename
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)

type _CanonicalNote = ObsidianNote | ObsidianNoteIndex


class ObsidianCanonicalIdentityService:
    """Resolve exact paths and report aliases without domain-specific hardcoding."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        vault_config_store: ObsidianVaultConfigStore,
    ) -> None:
        """Initialize ObsidianCanonicalIdentityService state and dependencies.

        Args:
            obsidian_service: Obsidian service dependency.
            vault_config_store: Vault config store used by this operation.
        """
        self._obsidian_service = obsidian_service
        self._vault_config_store = vault_config_store

    async def check_path(self, path: str) -> ObsidianExactPathStatus:
        """Return exact managed-path existence without fuzzy search fallback.

        Args:
            path: Value supplied to check_path.

        Returns:
            Result produced by check_path.
        """
        canonical_path = self._canonical_path(path)
        try:
            note = await self._obsidian_service.read_note_by_path(canonical_path)
        except ObsidianNotFoundError:
            return ObsidianExactPathStatus(
                exists=False,
                relative_path=canonical_path,
            )
        return ObsidianExactPathStatus(
            exists=True,
            relative_path=canonical_path,
            note_id=note.note_id,
            index_status=note.index_status,
        )

    async def resolve(
        self,
        project: str,
        report: str,
        date: str,
        entity: str,
        edition: str | None = None,
    ) -> ObsidianCanonicalIdentityResult:
        """Resolve one logical report identity using canonical metadata and aliases.

        Args:
            project: Value supplied to resolve.
            report: Value supplied to resolve.
            date: Value supplied to resolve.
            entity: Value supplied to resolve.
            edition: Value supplied to resolve.
        Returns:
            Result produced by resolve.
        """
        try:
            parsed_date = calendar_date.fromisoformat(date)
        except ValueError as exc:
            raise ObsidianValidationError(
                "date must be a valid ISO calendar date"
            ) from exc
        snapshot = await self._source_snapshot()
        return self._resolve_candidates(
            project=project,
            report=report,
            date=date,
            entity=entity,
            edition=edition,
            parsed_date=parsed_date,
            candidates=list(snapshot.notes),
            active_only=False,
        )

    async def resolve_logical_identity(
        self,
        identity: ObsidianLogicalIdentity,
    ) -> ObsidianCanonicalIdentityResult:
        """Resolve one shared logical identity against current active notes.

        This is the high-level write boundary. The existing scalar ``resolve``
        method remains available for diagnostics and legacy callers, while this
        entry point makes lifecycle eligibility explicit for agent writes.

        Args:
            identity: Shared logical identity to resolve.

        Returns:
            Current canonical identity resolution.
        """
        try:
            parsed_date = calendar_date.fromisoformat(identity.date)
        except ValueError as exc:
            raise ObsidianValidationError(
                "date must be a valid ISO calendar date"
            ) from exc
        snapshot = await self._source_snapshot()
        return self._resolve_candidates(
            project=identity.project,
            report=identity.report,
            date=identity.date,
            entity=identity.entity,
            edition=identity.edition,
            parsed_date=parsed_date,
            candidates=list(snapshot.notes),
            active_only=True,
        )

    async def _source_snapshot(self) -> ObsidianVaultSourceSnapshot:
        """Read one complete bounded source snapshot for identity resolution."""
        snapshot = await self._obsidian_service.source_snapshot(max_notes=4096)
        if not snapshot.complete or snapshot.errors:
            raise ObsidianValidationError(
                "SOURCE_SNAPSHOT_INCOMPLETE: canonical identity requires a "
                "complete source snapshot"
            )
        return snapshot

    def _resolve_candidates(
        self,
        project: str,
        report: str,
        date: str,
        entity: str,
        edition: str | None,
        parsed_date: calendar_date,
        candidates: list[_CanonicalNote],
        active_only: bool,
    ) -> ObsidianCanonicalIdentityResult:
        """Resolve one already-loaded source snapshot without additional reads."""
        matches: list[tuple[_CanonicalNote, str, tuple[str, ...]]] = []
        family_candidates: list[_CanonicalNote] = []
        for note in candidates:
            family = _text(note.frontmatter.get("report_family")) or _text(
                note.frontmatter.get("report")
            )
            if not family:
                continue
            aliases = _aliases(note)
            if _family_matches(
                note,
                project=project,
                family=family,
                requested_report=report,
                entity=entity,
                aliases=aliases,
            ):
                family_candidates.append(note)
            if _identity_matches(
                note,
                project=project,
                family=family,
                requested_report=report,
                date=date,
                entity=entity,
                edition=edition,
                aliases=aliases,
                active_only=active_only,
            ):
                matches.append((note, family, aliases))

        if len(matches) == 1:
            note, family, aliases = matches[0]
            return ObsidianCanonicalIdentityResult(
                canonical_report_family=family,
                canonical_entity=_text(note.frontmatter.get("entity")) or entity,
                canonical_path=note.relative_path,
                existing_note_id=note.note_id,
                aliases=aliases,
                resolution="EXISTING_CANONICAL_FAMILY",
            )
        generated_path = self._generated_path(
            project=project,
            report=report,
            parsed_date=parsed_date,
            entity=entity,
            edition=edition,
            family_candidates=family_candidates,
        )
        if len(matches) > 1:
            return ObsidianCanonicalIdentityResult(
                canonical_report_family=report,
                canonical_entity=entity,
                canonical_path=generated_path,
                existing_note_id=None,
                aliases=(),
                resolution="AMBIGUOUS_CANONICAL_IDENTITY",
                candidate_paths=tuple(item[0].relative_path for item in matches),
            )
        return ObsidianCanonicalIdentityResult(
            canonical_report_family=report,
            canonical_entity=entity,
            canonical_path=generated_path,
            existing_note_id=None,
            aliases=(),
            resolution="NEW_CANONICAL_IDENTITY",
        )

    def _canonical_path(self, path: str) -> str:
        """Execute canonical path.

        Args:
            path: Path used by this operation.

        Returns:
            str result produced by canonical path.
        """
        return canonical_managed_note_path(
            path,
            alexandria_root=self._vault_config_store.current().alexandria_root,
        )

    def _generated_path(
        self,
        project: str,
        report: str,
        parsed_date: calendar_date,
        entity: str,
        edition: str | None,
        family_candidates: list[_CanonicalNote],
    ) -> str:
        """Execute generated path.

        Args:
            project: Project used by this operation.
            report: Report used by this operation.
            parsed_date: Parsed date used by this operation.
            entity: Entity used by this operation.
            edition: Edition used by this operation.
            family_candidates: Family candidates used by this operation.

        Returns:
            str result produced by generated path.
        """
        inherited_path = _latest_inherited_path(
            family_candidates,
            target_date=parsed_date,
        )
        if inherited_path is not None:
            return self._canonical_path(inherited_path)

        title_parts = [project, report, entity, parsed_date.isoformat()]
        if edition:
            title_parts.append(edition)
        relative = "/".join(
            [
                "Contexts",
                "Projects",
                project,
                "Daily",
                f"{parsed_date.year:04d}",
                f"{parsed_date.month:02d}",
                report,
                entity,
                safe_filename(" ".join(title_parts)),
            ]
        )
        return self._canonical_path(relative)


def _family_matches(
    note: _CanonicalNote,
    project: str,
    family: str,
    requested_report: str,
    entity: str,
    aliases: tuple[str, ...],
) -> bool:
    """Execute family matches.

    Args:
        note: Note used by this operation.
        project: Project used by this operation.
        family: Family used by this operation.
        requested_report: Requested report used by this operation.
        entity: Entity used by this operation.
        aliases: Aliases used by this operation.

    Returns:
        Whether family matches.
    """
    note_project = note.project or _text(note.frontmatter.get("project"))
    note_entity = _text(note.frontmatter.get("entity"))
    report_names = {_normalized(family), *(_normalized(alias) for alias in aliases)}
    return (
        _normalized(note_project) == _normalized(project)
        and _normalized(note_entity) == _normalized(entity)
        and _normalized(requested_report) in report_names
    )


def _latest_inherited_path(
    candidates: list[_CanonicalNote],
    target_date: calendar_date,
) -> str | None:
    """Execute latest inherited path.

    Args:
        candidates: Candidates used by this operation.
        target_date: Target date used by this operation.

    Returns:
        str | None result produced by latest inherited path.
    """
    dated_candidates: list[tuple[calendar_date, str]] = []
    for note in candidates:
        source_date_text = _text(note.frontmatter.get("date"))
        if source_date_text is None:
            continue
        try:
            source_date = calendar_date.fromisoformat(source_date_text)
        except ValueError:
            continue
        if source_date >= target_date:
            continue
        rendered_path = _render_inherited_path(
            note.relative_path,
            source_date=source_date,
            target_date=target_date,
        )
        if rendered_path is not None:
            dated_candidates.append((source_date, rendered_path))

    if not dated_candidates:
        return None
    latest_date = max(item[0] for item in dated_candidates)
    latest_paths = {
        path for source_date, path in dated_candidates if source_date == latest_date
    }
    if len(latest_paths) != 1:
        return None
    return latest_paths.pop()


def _render_inherited_path(
    relative_path: str,
    source_date: calendar_date,
    target_date: calendar_date,
) -> str | None:
    """Render inherited path.

    Args:
        relative_path: Relative path used by this operation.
        source_date: Source date used by this operation.
        target_date: Target date used by this operation.

    Returns:
        Rendered inherited path.
    """
    parts = relative_path.split("/")
    if not parts:
        return None

    source_iso = source_date.isoformat()
    target_iso = target_date.isoformat()
    filename = parts[-1]
    if filename.count(source_iso) != 1:
        return None
    parts[-1] = filename.replace(source_iso, target_iso, 1)

    source_year = f"{source_date.year:04d}"
    source_month = f"{source_date.month:02d}"
    target_year = f"{target_date.year:04d}"
    target_month = f"{target_date.month:02d}"
    period_updated = False
    for index in range(len(parts) - 2):
        if parts[index] == source_year and parts[index + 1] == source_month:
            parts[index] = target_year
            parts[index + 1] = target_month
            period_updated = True
            break

    if not period_updated and (
        source_date.year != target_date.year or source_date.month != target_date.month
    ):
        return None
    return "/".join(parts)


def _identity_matches(
    note: _CanonicalNote,
    project: str,
    family: str,
    requested_report: str,
    date: str,
    entity: str,
    edition: str | None,
    aliases: tuple[str, ...],
    active_only: bool = False,
) -> bool:
    """Execute identity matches.

    Args:
        note: Note used by this operation.
        project: Project used by this operation.
        family: Family used by this operation.
        requested_report: Requested report used by this operation.
        date: Date used by this operation.
        entity: Entity used by this operation.
        edition: Edition used by this operation.
        aliases: Aliases used by this operation.
        active_only: Whether inactive lifecycle records are excluded.

    Returns:
        Whether identity matches.
    """
    note_date = _text(note.frontmatter.get("date"))
    note_edition = _text(note.frontmatter.get("edition"))
    status = _normalized(_text(note.frontmatter.get("status")))
    return (
        (not active_only or status in {"active", "current"})
        and _family_matches(
            note,
            project=project,
            family=family,
            requested_report=requested_report,
            entity=entity,
            aliases=aliases,
        )
        and note_date == date
        and (edition is None or _normalized(note_edition) == _normalized(edition))
    )


def _aliases(note: _CanonicalNote) -> tuple[str, ...]:
    """Execute aliases.

    Args:
        note: Note used by this operation.

    Returns:
        tuple[str, ...] result produced by aliases.
    """
    values: list[str] = []
    for field in ("aliases", "report_aliases"):
        value = note.frontmatter.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return tuple(dict.fromkeys(values))


# Broad type justified: frontmatter lookup values may have heterogeneous runtime types.
def _text(value: object) -> str | None:
    """Execute text.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by text.
    """
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalized(value: str | None) -> str:
    """Execute normalized.

    Args:
        value: Value being processed.

    Returns:
        str result produced by normalized.
    """
    return "" if value is None else " ".join(value.casefold().split())
