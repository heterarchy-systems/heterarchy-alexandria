"""HTTP acquisition for the fixed multilingual-E5 artifact stream."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, BinaryIO
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    ASSET_NAMES,
    CHUNK_SIZE,
    AssetMetadata,
    SinkProtocol,
    StagedAsset,
    cache_error,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_session import (
    ArtifactCache,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_staging import (
    ArtifactStaging,
    staging_directory,
)
from app.platform.config.memory_config import (
    EmbeddingModelArtifactConfig,
)

_MODEL_ID = "intfloat/multilingual-e5-small"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 10
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


@dataclass(frozen=True, slots=True)
class _ModelMetadata:
    revision: str
    assets: dict[str, AssetMetadata]


class _HuggingFaceMetadataModel(BaseModel):
    """Open third-party metadata contract with strict known-field validation."""

    model_config = ConfigDict(
        extra="ignore",
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
    )


class _HuggingFaceLfsMetadata(_HuggingFaceMetadataModel):
    """Typed LFS identity fields returned by the model-info endpoint."""

    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
    size: Annotated[int, Field(gt=0)] | None = None


class _HuggingFaceSibling(_HuggingFaceMetadataModel):
    """One file entry in the third-party model-info response."""

    rfilename: str | None = None
    size: Annotated[int, Field(gt=0)] | None = None
    blob_id: (
        Annotated[
            str,
            StringConstraints(pattern=r"^[0-9a-fA-F]{40}$"),
        ]
        | None
    ) = Field(default=None, validation_alias="blobId")
    lfs: _HuggingFaceLfsMetadata | None = None


class _HuggingFaceModelInfo(_HuggingFaceMetadataModel):
    """Pydantic boundary for the raw Hugging Face model-info JSON response."""

    sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    siblings: list[_HuggingFaceSibling]

    @field_validator("siblings", mode="before")
    @classmethod
    def select_fixed_model_assets(cls, value: object) -> object:
        """Validate typed siblings only for the five files this runtime consumes."""
        if not isinstance(value, list):
            return value
        return [
            sibling
            for sibling in value
            if isinstance(sibling, dict) and sibling.get("rfilename") in ASSET_NAMES
        ]


def acquire_and_stream(
    cache: ArtifactCache,
    config: EmbeddingModelArtifactConfig,
    sink: SinkProtocol,
) -> str:
    """Acquire only after a cache miss, then publish and stream the pinned snapshot."""
    try:
        return _acquire_snapshot(cache, config, sink)
    except httpx.HTTPError:
        cache_error("cache or remote operation failed")


def _acquire_snapshot(
    cache: ArtifactCache,
    config: EmbeddingModelArtifactConfig,
    sink: SinkProtocol,
) -> str:
    """Repair the referenced commit or publish one newly resolved snapshot."""
    with cache.mutation_lock.exclusive_lock():
        revision = cache.reader.stream_complete_snapshot(sink)
        if revision is not None:
            return revision
        current_reference = cache.references.read_reference()
        requested_revision = (
            current_reference.revision if current_reference is not None else "main"
        )
        token = _read_token(config.token_path)
        with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
            model_metadata = _fetch_model_metadata(
                client,
                endpoint=config.endpoint,
                requested_revision=requested_revision,
                token=token,
            )
            if current_reference is not None and (
                model_metadata.revision != current_reference.revision
            ):
                cache_error("model metadata conflicts with cached reference")
            locations = cache.reader.inspect_snapshot_assets(model_metadata.revision)
            missing_names: list[str] = []
            for name in ASSET_NAMES:
                location = locations[name]
                metadata = model_metadata.assets[name]
                if location is None:
                    missing_names.append(name)
                else:
                    cache.reader.stream_cached_asset(location, metadata=metadata)
            with staging_directory(directory=cache.directory) as staging:
                staged_assets = _download_missing_assets(
                    client,
                    endpoint=config.endpoint,
                    revision=model_metadata.revision,
                    token=token,
                    model_metadata=model_metadata,
                    missing_names=missing_names,
                    staging=staging,
                )
                staging.fsync()
                cache.references.assert_reference_unchanged(
                    current_reference,
                    model_metadata.revision,
                )
                cache.reader.assert_assets_unchanged(locations)
                cache.publisher.publish_assets(
                    revision=model_metadata.revision,
                    locations=locations,
                    staged_assets=staged_assets,
                    staging=staging,
                )
        if current_reference is None:
            cache.references.publish_reference(model_metadata.revision)
        completed_revision = cache.reader.stream_complete_snapshot(
            sink,
            expected_revision=model_metadata.revision,
        )
        if completed_revision is None:
            cache_error("published snapshot is incomplete")
        return completed_revision


def _read_token(token_path: Path) -> str | None:
    """Read the one supported token file without exposing its contents."""
    try:
        content = token_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError, UnicodeError:
        cache_error("configured token file could not be read")
    token = content.strip()
    if any(character.isspace() for character in token):
        cache_error("configured token file is invalid")
    return token or None


def _fetch_model_metadata(
    client: httpx.Client,
    *,
    endpoint: str,
    requested_revision: str,
    token: str | None,
) -> _ModelMetadata:
    """Read one pinned model metadata response before any file request."""
    path = f"/api/models/{_MODEL_ID}/revision/{requested_revision}?blobs=true"
    response = _open_get_response(
        client,
        f"{endpoint.rstrip('/')}{path}",
        token=token,
        accept="application/json",
    )
    try:
        try:
            metadata = _HuggingFaceModelInfo.model_validate_json(response.read())
        except httpx.HTTPError, ValidationError:
            cache_error("model metadata response is invalid")
    finally:
        response.close()
    revision = metadata.sha
    if requested_revision != "main" and revision != requested_revision:
        cache_error("model metadata conflicts with requested revision")
    sibling_records: dict[str, _HuggingFaceSibling] = {}
    for sibling in metadata.siblings:
        name = sibling.rfilename
        if name is not None and name in ASSET_NAMES:
            if name in sibling_records:
                cache_error("model metadata contains duplicate fixed assets")
            sibling_records[name] = sibling
    assets: dict[str, AssetMetadata] = {}
    for name in ASSET_NAMES:
        sibling = sibling_records.get(name)
        if sibling is None:
            cache_error("model metadata is missing a required asset")
        assets[name] = _parse_asset_metadata(name, sibling)
    return _ModelMetadata(revision=revision, assets=assets)


def _parse_asset_metadata(
    name: str,
    sibling: _HuggingFaceSibling,
) -> AssetMetadata:
    """Validate length and available LFS or Git identity for one known asset."""
    lfs_sha256: str | None = None
    lfs_size: int | None = None
    if sibling.lfs is not None:
        lfs_sha256 = sibling.lfs.sha256.lower()
        lfs_size = sibling.lfs.size
    size = sibling.size if sibling.size is not None else lfs_size
    if size is None:
        cache_error("model metadata declared length is missing")
    if lfs_size is not None and lfs_size != size:
        cache_error("model metadata declared lengths conflict")
    git_blob_sha1: str | None = None
    if lfs_sha256 is None and sibling.blob_id is not None:
        git_blob_sha1 = sibling.blob_id.lower()
    return AssetMetadata(name, size, lfs_sha256, git_blob_sha1)


def _open_get_response(
    client: httpx.Client,
    url: str,
    *,
    token: str | None,
    accept: str,
) -> httpx.Response:
    """Issue one GET and handle redirects without forwarding credentials cross-origin."""
    headers = {"Accept": accept, "Accept-Encoding": "identity"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    initial_scheme = urlsplit(url).scheme
    authenticated_https = token is not None and initial_scheme == "https"
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            request = client.build_request("GET", current_url, headers=headers)
            response = client.send(request, stream=True)
        except httpx.HTTPError:
            cache_error("remote model request failed")
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("location")
            response.close()
            if location is None:
                cache_error("remote model redirect is invalid")
            try:
                next_url = urljoin(current_url, location)
                next_parts = urlsplit(next_url)
            except ValueError:
                cache_error("remote model redirect is invalid")
            next_origin = _origin(next_url)
            if (
                next_parts.scheme not in {"http", "https"}
                or next_parts.hostname is None
                or next_parts.username is not None
                or next_parts.password is not None
            ):
                cache_error("remote model redirect is invalid")
            if authenticated_https and next_parts.scheme != "https":
                cache_error("authenticated HTTPS downgrade rejected")
            if _origin(current_url) != next_origin:
                headers.pop("Authorization", None)
                headers.pop("Cookie", None)
                client.cookies.clear()
            current_url = next_url
            continue
        if response.status_code < 200 or response.status_code >= 300:
            response.close()
            cache_error("remote model request failed")
        return response
    cache_error("remote model redirect limit exceeded")


def _origin(url: str) -> tuple[str, str, int]:
    """Return normalized HTTP origin components for redirect credential checks."""
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    if scheme not in {"http", "https"} or host is None:
        cache_error("remote model redirect is invalid")
    try:
        port = parsed.port
    except ValueError:
        cache_error("remote model redirect is invalid")
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, host.lower(), port


def _download_missing_assets(
    client: httpx.Client,
    *,
    endpoint: str,
    revision: str,
    token: str | None,
    model_metadata: _ModelMetadata,
    missing_names: list[str],
    staging: ArtifactStaging,
) -> dict[str, StagedAsset]:
    """Stream and validate all missing fixed assets into private staging files."""
    staged: dict[str, StagedAsset] = {}
    for index, name in enumerate(ASSET_NAMES):
        if name not in missing_names:
            continue
        metadata = model_metadata.assets[name]
        stage_name = f"asset-{index}.part"
        asset_url = f"{endpoint.rstrip('/')}/{_MODEL_ID}/resolve/{revision}/{name}"
        response = _open_get_response(
            client,
            asset_url,
            token=token,
            accept="application/octet-stream",
        )
        try:
            with staging.create_file(stage_name) as stream:
                digest = _stream_asset_to_file(
                    response,
                    stream,
                    metadata,
                    need_sha256=(
                        metadata.lfs_sha256 is not None
                        or metadata.git_blob_sha1 is None
                    ),
                    need_git_sha1=metadata.git_blob_sha1 is not None,
                )
        finally:
            response.close()
        _validate_download_digest(metadata, digest)
        blob_name = metadata.lfs_sha256 or metadata.git_blob_sha1 or digest[1]
        if blob_name is None:
            cache_error("downloaded asset cache identity is unavailable")
        staged[name] = StagedAsset(metadata, stage_name, blob_name)
    return staged


def _stream_asset_to_file(
    response: httpx.Response,
    stream: BinaryIO,
    metadata: AssetMetadata,
    *,
    need_sha256: bool,
    need_git_sha1: bool,
) -> tuple[int, str | None, str | None]:
    """Stream one response and hash it while writing to an owned stage file."""
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_header_length = int(content_length)
        except ValueError:
            cache_error("downloaded asset length header is invalid")
        if declared_header_length != metadata.size:
            cache_error("downloaded asset length mismatch")
    byte_count = 0
    raw_sha256 = hashlib.sha256() if need_sha256 else None
    git_sha1 = hashlib.sha1() if need_git_sha1 else None
    if git_sha1 is not None:
        git_sha1.update(f"blob {metadata.size}\0".encode("ascii"))
    try:
        for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
            if not chunk:
                continue
            byte_count += len(chunk)
            if byte_count > metadata.size:
                cache_error("downloaded asset length mismatch")
            if raw_sha256 is not None:
                raw_sha256.update(chunk)
            if git_sha1 is not None:
                git_sha1.update(chunk)
            stream.write(chunk)
        if byte_count != metadata.size:
            cache_error("downloaded asset length mismatch")
    except httpx.HTTPError:
        cache_error("model asset download failed")
    return (
        byte_count,
        raw_sha256.hexdigest() if raw_sha256 is not None else None,
        git_sha1.hexdigest() if git_sha1 is not None else None,
    )


def _validate_download_digest(
    metadata: AssetMetadata,
    digest: tuple[int, str | None, str | None],
) -> None:
    """Check available LFS SHA256 or Git blob identity against streamed bytes."""
    if metadata.lfs_sha256 is not None and digest[1] != metadata.lfs_sha256:
        cache_error("downloaded asset identity mismatch")
    if metadata.git_blob_sha1 is not None and digest[2] != metadata.git_blob_sha1:
        cache_error("downloaded asset identity mismatch")
