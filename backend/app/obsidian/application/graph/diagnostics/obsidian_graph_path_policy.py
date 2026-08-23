"""Safe Markdown and wikilink target normalization for graph relations."""

from __future__ import annotations

import re

from app.obsidian.application.graph.relations.obsidian_graph_relation_contracts import (
    _ROOT_RELATIVE_LINK_PREFIXES,
    _WIKILINK_RE,
)

_NON_NOTE_REFERENCE_PREFIXES = ("artifact:", "evidence:")


def _wikilink_targets(
    body: str,
    relative_path: str,
    alexandria_root: str,
) -> list[str]:
    """Execute wikilink targets.

    Args:
        body: Body used by this operation.
        relative_path: Relative path used by this operation.
        alexandria_root: Alexandria root used by this operation.

    Returns:
        list[str] result produced by wikilink targets.
    """
    targets: list[str] = []
    for match in _WIKILINK_RE.finditer(_linkable_markdown(body)):
        target = _normalize_wikilink_target_path(
            match.group(1),
            relative_path=relative_path,
            alexandria_root=alexandria_root,
        )
        if target is not None:
            targets.append(target)
    return targets


def _normalize_wikilink_target_path(
    path: str | None,
    relative_path: str,
    alexandria_root: str,
) -> str | None:
    """Normalize wikilink target path.

    Args:
        path: Path used by this operation.
        relative_path: Relative path used by this operation.
        alexandria_root: Alexandria root used by this operation.

    Returns:
        Normalized wikilink target path.
    """
    normalized = _normalize_markdown_target(path)
    if normalized is None:
        return None
    root = alexandria_root.strip().strip("/") or "."
    first_segment = normalized.split("/", maxsplit=1)[0]
    if root != "." and normalized.startswith(f"{root}/"):
        return normalized
    if first_segment in _ROOT_RELATIVE_LINK_PREFIXES:
        return normalized if root == "." else f"{root}/{normalized}"
    del relative_path
    return normalized if root == "." else f"{root}/{normalized}"


def _normalize_target_path(path: str | None, alexandria_root: str) -> str | None:
    """Normalize target path.

    Args:
        path: Path used by this operation.
        alexandria_root: Alexandria root used by this operation.

    Returns:
        Normalized target path.
    """
    normalized = _normalize_markdown_target(path)
    if normalized is None:
        return None
    root = alexandria_root.strip().strip("/") or "."
    if root == ".":
        return normalized
    if "/" in normalized:
        if normalized.startswith(f"{root}/"):
            return normalized
        return f"{root}/{normalized}"
    return f"{root}/{normalized}"


def _normalize_markdown_target(path: str | None) -> str | None:
    """Normalize markdown target.

    Args:
        path: Path used by this operation.

    Returns:
        Normalized markdown target.
    """
    if path is None:
        return None
    normalized = path.strip()
    if normalized.startswith("[[") and normalized.endswith("]]"):
        normalized = normalized[2:-2].split("|", maxsplit=1)[0]
        normalized = normalized.split("#", maxsplit=1)[0]
    normalized = normalized.removeprefix("./")
    if (
        not normalized
        or "://" in normalized
        or normalized.startswith("#")
        or normalized.casefold().startswith(_NON_NOTE_REFERENCE_PREFIXES)
    ):
        return None
    normalized = normalized.removesuffix(".md") + ".md"
    if normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    return normalized


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_OBSIDIAN_COMMENT_RE = re.compile(r"%%.*?%%", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"(?P<ticks>`+).*?(?P=ticks)", re.DOTALL)
_FENCE_START_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")


def _linkable_markdown(body: str) -> str:
    """Remove comments and code regions that Obsidian does not render as links.

    Args:
        body: Body used by this operation.

    Returns:
        str result produced by linkable markdown.
    """
    visible_lines: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in body.splitlines(keepends=True):
        stripped = line.lstrip(" \t")
        if fence_character is not None:
            closing = stripped.rstrip("\r\n").rstrip()
            if (
                closing
                and set(closing) == {fence_character}
                and len(closing) >= fence_length
            ):
                fence_character = None
                fence_length = 0
            visible_lines.append("\n" if line.endswith("\n") else "")
            continue
        fence_match = _FENCE_START_RE.match(line)
        if fence_match is not None:
            fence = fence_match.group("fence")
            fence_character = fence[0]
            fence_length = len(fence)
            visible_lines.append("\n" if line.endswith("\n") else "")
            continue
        if line.startswith(("    ", "\t")):
            visible_lines.append("\n" if line.endswith("\n") else "")
            continue
        visible_lines.append(line)
    visible = "".join(visible_lines)
    visible = _HTML_COMMENT_RE.sub("", visible)
    visible = _OBSIDIAN_COMMENT_RE.sub("", visible)
    return _INLINE_CODE_RE.sub("", visible)
