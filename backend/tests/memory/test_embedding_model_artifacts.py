"""Python-owned embedding artifact acquisition contracts."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha1, sha256
from io import BytesIO
from pathlib import Path
from typing import cast

import httpx
import pytest

import app.memory.infrastructure.providers.embedding_model_artifacts as artifact_io
from app.memory.infrastructure.providers.artifact_cache import regular_files as cache_fs
from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    AssetMetadata,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_session import (
    ArtifactCache,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_staging import (
    staging_directory,
)
from app.memory.infrastructure.providers.embedding_model_artifacts import (
    EmbeddingModelArtifactSink,
    stream_embedding_model_artifacts,
)
from app.platform.config.memory_config import (
    EmbeddingModelArtifactConfig,
)

MODEL_ID = "intfloat/multilingual-e5-small"
REVISION = "a" * 40
OTHER_REVISION = "b" * 40
MODEL_CACHE_NAME = "models--intfloat--multilingual-e5-small"
MAX_TEST_CHUNK_SIZE = 1024 * 1024
ASSET_BYTES: dict[str, bytes] = {
    "onnx/model.onnx": b"fixture-onnx-model",
    "tokenizer.json": b"fixture-tokenizer-json",
    "config.json": b"fixture-model-config",
    "special_tokens_map.json": b"fixture-special-tokens",
    "tokenizer_config.json": b"fixture-tokenizer-config",
}


class _CapturingSink:
    """Test-only receiver for the tiny deterministic artifact fixtures."""

    def __init__(self) -> None:
        self.asset_sizes: dict[str, int] = {}
        self.asset_contents: dict[str, bytearray] = {}
        self.max_chunk_size = 0
        self._active_asset: str | None = None
        self.verified_assets: list[str] = []

    def begin_asset(self, name: str, size: int) -> None:
        if (
            self._active_asset is not None
            and len(self.asset_contents[self._active_asset])
            != self.asset_sizes[self._active_asset]
        ):
            raise AssertionError("previous asset was incomplete")
        if name in self.asset_sizes:
            raise AssertionError("asset was begun more than once")
        self.asset_sizes[name] = size
        self.asset_contents[name] = bytearray()
        self._active_asset = name

    def write_chunk(self, chunk: bytes) -> None:
        if self._active_asset is None:
            raise AssertionError("asset chunk arrived before begin_asset")
        if len(chunk) > MAX_TEST_CHUNK_SIZE:
            raise AssertionError("asset chunk exceeded the fixed IO chunk size")
        self.max_chunk_size = max(self.max_chunk_size, len(chunk))
        self.asset_contents[self._active_asset].extend(chunk)

    def asset_verified(self, name: str) -> None:
        if self._active_asset != name:
            raise AssertionError("asset verification did not match the active asset")
        if len(self.asset_contents[name]) != self.asset_sizes[name]:
            raise AssertionError("asset was verified before its full content arrived")
        self.verified_assets.append(name)
        self._active_asset = None

    def content_by_name(self) -> dict[str, bytes]:
        return {name: bytes(content) for name, content in self.asset_contents.items()}


@dataclass(frozen=True, slots=True)
class _CapturedArtifacts:
    """Test-only captured output; production exposes only the revision string."""

    revision: str
    sink: _CapturingSink


def _capture_stream(
    cache_dir: str | None,
    config: EmbeddingModelArtifactConfig,
) -> _CapturedArtifacts:
    """Capture tiny fixtures through the same public sink contract as native code."""
    capturing_sink = _CapturingSink()
    sink: EmbeddingModelArtifactSink = capturing_sink
    revision = stream_embedding_model_artifacts(cache_dir, config, sink)
    assert tuple(capturing_sink.asset_sizes) == tuple(ASSET_BYTES)
    assert all(
        capturing_sink.asset_sizes[name] == len(ASSET_BYTES[name])
        and len(capturing_sink.asset_contents[name]) == capturing_sink.asset_sizes[name]
        for name in ASSET_BYTES
    )
    assert capturing_sink.verified_assets == list(ASSET_BYTES)
    return _CapturedArtifacts(revision, capturing_sink)


def _git_blob_id(content: bytes) -> str:
    """Return Git's content-addressed identity for one fixture file."""
    digest = sha1()
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return digest.hexdigest()


def _metadata(
    revision: str,
    assets: dict[str, bytes] = ASSET_BYTES,
    *,
    size_delta: int = 0,
    lfs_digest_override: str | None = None,
) -> dict[str, object]:
    """Build model API metadata with Git blob and LFS identities."""
    siblings: list[dict[str, object]] = []
    for name, content in assets.items():
        size = len(content) + (size_delta if name == "tokenizer.json" else 0)
        item: dict[str, object] = {"rfilename": name, "size": size}
        if name in {"onnx/model.onnx", "tokenizer.json"}:
            lfs_digest = lfs_digest_override or sha256(content).hexdigest()
            item["lfs"] = {
                "sha256": lfs_digest,
                "size": len(content),
                "pointerSize": 128,
            }
        else:
            item["blobId"] = _git_blob_id(content)
        siblings.append(item)
    siblings.append(
        {
            "rfilename": "README.md",
            "size": 7,
            "ignoredExtra": {"model": "unrelated"},
        }
    )
    return {"sha": revision, "siblings": siblings}


def _cache_root(tmp_path: Path) -> Path:
    """Return an isolated configured HF cache root."""
    return tmp_path / "cache"


def _model_dir(cache_root: Path) -> Path:
    """Return the fixed Hugging Face model cache directory."""
    return cache_root / MODEL_CACHE_NAME


def _snapshot_path(cache_root: Path, revision: str, name: str) -> Path:
    """Return the fixed asset path in one immutable snapshot."""
    return _model_dir(cache_root) / "snapshots" / revision / name


def _filesystem_state(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    """Capture only a test cache's entries and tiny fixture contents."""
    if not root.exists():
        return {}
    state: dict[str, tuple[str, bytes | str | None]] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[relative] = ("symlink", os.readlink(path))
        elif path.is_file():
            state[relative] = ("file", path.read_bytes())
        elif path.is_dir():
            state[relative] = ("directory", None)
    return state


def _blob_name(name: str, content: bytes) -> str:
    """Return the fixture blob identity used by the HF cache layout."""
    if name in {"onnx/model.onnx", "tokenizer.json"}:
        return sha256(content).hexdigest()
    return _git_blob_id(content)


def _write_snapshot(
    cache_root: Path,
    revision: str,
    *,
    missing: frozenset[str] = frozenset(),
    contents: dict[str, bytes] = ASSET_BYTES,
) -> None:
    """Create a Hugging Face snapshot using confined blob symlinks."""
    model_dir = _model_dir(cache_root)
    (model_dir / "refs").mkdir(parents=True, exist_ok=True)
    (model_dir / "blobs").mkdir(parents=True, exist_ok=True)
    snapshot = model_dir / "snapshots" / revision
    for name, content in contents.items():
        if name in missing:
            continue
        blob = model_dir / "blobs" / _blob_name(name, content)
        blob.write_bytes(content)
        asset = snapshot / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.symlink_to(os.path.relpath(blob, start=asset.parent))
    (model_dir / "refs" / "main").write_text(f"{revision}\n", encoding="ascii")


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Force every loader HTTP request through a local MockTransport handler."""
    import app.memory.infrastructure.providers.embedding_model_artifact_acquisition as acquisition_io

    real_client = httpx.Client

    def mock_client(*, timeout: httpx.Timeout, follow_redirects: bool) -> httpx.Client:
        return real_client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(acquisition_io.httpx, "Client", mock_client)


def _client_asset_name(request: httpx.Request, revision: str) -> str:
    """Extract a fixture asset only from the fixed resolve route."""
    marker = f"/resolve/{revision}/"
    path = request.url.path
    assert marker in path
    return path.split(marker, maxsplit=1)[1]


def _response_for_model_request(
    request: httpx.Request,
    *,
    revision: str,
    content_by_asset: dict[str, bytes] = ASSET_BYTES,
    model_metadata: dict[str, object] | None = None,
) -> httpx.Response:
    """Serve deterministic metadata and asset bytes for one test request."""
    metadata_path = f"/api/models/{MODEL_ID}/revision/{revision}"
    if request.url.path == metadata_path:
        return httpx.Response(
            200,
            request=request,
            json=model_metadata or _metadata(revision, content_by_asset),
        )
    marker = f"/resolve/{revision}/"
    if marker in request.url.path:
        asset = _client_asset_name(request, revision)
        content = content_by_asset.get(asset)
        if content is None:
            return httpx.Response(404, request=request)
        return httpx.Response(200, request=request, content=content)
    return httpx.Response(404, request=request)


def _settings(
    cache_root: Path,
    *,
    hf_home: Path | None = None,
    token_path: Path | None = None,
    endpoint: str = "https://huggingface.co",
) -> EmbeddingModelArtifactConfig:
    """Build explicit isolated settings for one artifact test."""
    config = EmbeddingModelArtifactConfig(
        _env_file=None,
        hf_home=hf_home,
        fallback_cache_dir=cache_root,
        endpoint=endpoint,
        ort_load_config_from_model=None,
        token_path=(
            token_path
            if token_path is not None
            else cache_root.parent / "synthetic-token"
        ),
    )
    return config


def test_complete_snapshot_is_read_only_offline_hit_without_token_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A complete immutable cache is readable offline even when its root is read-only."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)
    token_path = tmp_path / "token-is-a-directory"
    token_path.mkdir()
    model_dir = _model_dir(cache_root)
    directories = [
        cache_root,
        model_dir,
        model_dir / "refs",
        model_dir / "blobs",
        model_dir / "snapshots",
        model_dir / "snapshots" / REVISION,
        model_dir / "snapshots" / REVISION / "onnx",
    ]
    original_modes = {path: path.stat().st_mode for path in directories}
    before = set(cache_root.rglob("*"))
    for directory in directories:
        directory.chmod(0o555)
    _install_mock_transport(
        monkeypatch,
        lambda request: httpx.Response(500, request=request),
    )

    try:
        artifacts = _capture_stream(
            None,
            _settings(cache_root, token_path=token_path),
        )
    finally:
        for directory, mode in original_modes.items():
            directory.chmod(mode & 0o777)

    assert artifacts.revision == REVISION
    assert artifacts.sink.content_by_name() == ASSET_BYTES
    assert set(cache_root.rglob("*")) == before


def test_cache_only_stream_reuses_complete_snapshot_without_cache_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The cache-only API streams complete data but never creates a lock or reads auth."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)
    token_path = tmp_path / "token-is-a-directory"
    token_path.mkdir()
    before = _filesystem_state(cache_root)
    requests: list[httpx.Request] = []
    _install_mock_transport(
        monkeypatch,
        lambda request: (
            requests.append(request) or httpx.Response(500, request=request)
        ),
    )
    config = _settings(cache_root, token_path=token_path)
    sink = _CapturingSink()

    revision = artifact_io.stream_cached_embedding_model_artifacts(
        None,
        config,
        sink,
    )

    assert revision == REVISION
    assert sink.content_by_name() == ASSET_BYTES
    assert sink.verified_assets == list(ASSET_BYTES)
    assert requests == []
    assert _filesystem_state(cache_root) == before


@pytest.mark.parametrize("cache_state", ("absent", "partial"))
def test_cache_only_stream_stops_before_sink_or_effects_for_absent_or_partial_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cache_state: str,
) -> None:
    """Absent and incomplete caches return None without token, HTTP, or publication."""
    cache_root = _cache_root(tmp_path)
    if cache_state == "partial":
        _write_snapshot(
            cache_root,
            REVISION,
            missing=frozenset({"tokenizer_config.json"}),
        )
    before = _filesystem_state(cache_root)
    token_path = tmp_path / "token-is-a-directory"
    token_path.mkdir()
    requests: list[httpx.Request] = []
    _install_mock_transport(
        monkeypatch,
        lambda request: (
            requests.append(request) or httpx.Response(500, request=request)
        ),
    )
    sink = _CapturingSink()

    revision = artifact_io.stream_cached_embedding_model_artifacts(
        None,
        _settings(cache_root, token_path=token_path),
        sink,
    )

    assert revision is None
    assert sink.asset_sizes == {}
    assert sink.verified_assets == []
    assert requests == []
    assert _filesystem_state(cache_root) == before


@pytest.mark.parametrize("cache_state", ("complete", "partial", "absent"))
def test_read_only_paths_do_not_import_http_acquisition_in_fresh_process(
    tmp_path: Path,
    cache_state: str,
) -> None:
    """Healthy and cache-only paths leave HTTPX and acquisition schemas unloaded."""
    cache_root = _cache_root(tmp_path)
    if cache_state == "complete":
        _write_snapshot(cache_root, REVISION)
    elif cache_state == "partial":
        _write_snapshot(
            cache_root,
            REVISION,
            missing=frozenset({"tokenizer_config.json"}),
        )
    child_source = """
import socket
import sys
from pathlib import Path

from app.memory.infrastructure.providers.embedding_model_artifacts import (
    stream_cached_embedding_model_artifacts,
    stream_embedding_model_artifacts,
)
from app.platform.config.memory_config import (
    EmbeddingModelArtifactConfig,
)

def deny_network(*args, **kwargs):
    raise AssertionError("read-only artifact path attempted network access")

socket.getaddrinfo = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network

class Sink:
    def begin_asset(self, name: str, size: int) -> None:
        return None

    def write_chunk(self, chunk: bytes) -> None:
        return None

    def asset_verified(self, name: str) -> None:
        return None

cache_root = Path(sys.argv[1])
expected_revision = sys.argv[2]
cache_state = sys.argv[3]
config = EmbeddingModelArtifactConfig(
    _env_file=None,
    hf_home=None,
    fallback_cache_dir=cache_root,
    endpoint="http://127.0.0.1:1",
    ort_load_config_from_model=None,
    token_path=cache_root.parent / "synthetic-token",
)
if cache_state == "complete":
    revision = stream_embedding_model_artifacts(None, config, Sink())
    assert revision == expected_revision
else:
    revision = stream_cached_embedding_model_artifacts(None, config, Sink())
    assert revision is None
assert "httpx" not in sys.modules
assert "app.memory.infrastructure.providers.embedding_model_artifact_acquisition" not in sys.modules
"""
    child_env = os.environ.copy()
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    child_env["HOME"] = str(tmp_path / "isolated-home")
    child_env["HF_ENDPOINT"] = "http://127.0.0.1:1"
    child_env.pop("ORT_LOAD_CONFIG_FROM_MODEL", None)

    subprocess.run(
        [sys.executable, "-c", child_source, str(cache_root), REVISION, cache_state],
        cwd=Path.cwd(),
        env=child_env,
        capture_output=True,
        check=True,
        text=True,
    )


def test_complete_snapshot_rejects_corrupted_known_blob_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Offline snapshot reads verify every available HF blob identity."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)
    model_dir = _model_dir(cache_root)
    blob_name = _blob_name(
        "onnx/model.onnx",
        ASSET_BYTES["onnx/model.onnx"],
    )
    (model_dir / "blobs" / blob_name).write_bytes(b"tampered-onnx-bytes")
    requests: list[httpx.Request] = []
    _install_mock_transport(
        monkeypatch,
        lambda request: (
            requests.append(request) or httpx.Response(500, request=request)
        ),
    )

    def unnecessary_sha1(*args: object, **kwargs: object) -> object:
        raise AssertionError("LFS assets must not compute Git SHA1")

    monkeypatch.setattr(cache_fs.hashlib, "sha1", unnecessary_sha1)

    sink = _CapturingSink()
    with pytest.raises(ValueError, match="identity mismatch"):
        artifact_io.stream_cached_embedding_model_artifacts(
            None,
            _settings(cache_root),
            sink,
        )

    assert sink.verified_assets == []
    assert sink.asset_sizes == {"onnx/model.onnx": len(b"tampered-onnx-bytes")}
    assert requests == []


def test_final_reference_fence_runs_after_each_verified_asset_notification(
    tmp_path: Path,
) -> None:
    """Every asset is individually verified, then final ref drift still fails."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)

    class _ReferenceDriftingSink(_CapturingSink):
        def asset_verified(self, name: str) -> None:
            super().asset_verified(name)
            if name == "onnx/model.onnx":
                (_model_dir(cache_root) / "refs" / "main").write_text(
                    f"{OTHER_REVISION}\n",
                    encoding="ascii",
                )

    sink = _ReferenceDriftingSink()
    with pytest.raises(ValueError, match="cached reference changed during read"):
        artifact_io.stream_cached_embedding_model_artifacts(
            None,
            _settings(cache_root),
            sink,
        )

    assert sink.verified_assets == list(ASSET_BYTES)


def test_complete_snapshot_streams_within_fixed_chunks(
    tmp_path: Path,
) -> None:
    """Streaming uses bounded IO chunks without imposing a model-size ceiling."""
    cache_root = _cache_root(tmp_path)
    large_onnx = b"x" * (MAX_TEST_CHUNK_SIZE + 7)
    contents = {**ASSET_BYTES, "onnx/model.onnx": large_onnx}
    _write_snapshot(cache_root, REVISION, contents=contents)
    sink = _CapturingSink()
    config = _settings(cache_root)

    revision = stream_embedding_model_artifacts(None, config, sink)

    assert revision == REVISION
    assert sink.asset_sizes["onnx/model.onnx"] == len(large_onnx)
    assert bytes(sink.asset_contents["onnx/model.onnx"]) == large_onnx
    assert sink.max_chunk_size == MAX_TEST_CHUNK_SIZE


def test_streaming_computes_only_the_required_lfs_or_git_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """LFS assets use SHA256 only; Git-backed assets use the framed Git SHA1."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)
    _install_mock_transport(
        monkeypatch,
        lambda request: httpx.Response(500, request=request),
    )
    active_asset: list[str | None] = [None]
    sha1_assets: list[str] = []
    original_sha1 = sha1

    class _DigestRecordingSink(_CapturingSink):
        def begin_asset(self, name: str, size: int) -> None:
            active_asset[0] = name
            super().begin_asset(name, size)

    def record_sha1(*args: object, **kwargs: object) -> object:
        name = active_asset[0]
        if name is None or name in {"onnx/model.onnx", "tokenizer.json"}:
            raise AssertionError("unneeded Git SHA1 was calculated")
        sha1_assets.append(name)
        return original_sha1(*args, **kwargs)

    monkeypatch.setattr(cache_fs.hashlib, "sha1", record_sha1)
    sink = _DigestRecordingSink()

    revision = stream_embedding_model_artifacts(None, _settings(cache_root), sink)

    assert revision == REVISION
    assert sha1_assets == [
        "config.json",
        "special_tokens_map.json",
        "tokenizer_config.json",
    ]


def test_lfs_download_hashes_only_sha256_and_rejects_a_wrong_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LFS transfer avoids Git SHA1 while still failing a mismatched SHA256."""
    import app.memory.infrastructure.providers.embedding_model_artifact_acquisition as acquisition_io

    content = ASSET_BYTES["onnx/model.onnx"]
    expected_sha256 = sha256(content).hexdigest()
    metadata = AssetMetadata(
        "onnx/model.onnx",
        len(content),
        expected_sha256,
        None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, content=content)

    def unexpected_sha1(*args: object, **kwargs: object) -> object:
        raise AssertionError("LFS transfer must not compute Git SHA1")

    monkeypatch.setattr(cache_fs.hashlib, "sha1", unexpected_sha1)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = client.send(
            client.build_request("GET", "https://fixture.example/model.onnx"),
            stream=True,
        )
        try:
            destination = BytesIO()
            digest = acquisition_io._stream_asset_to_file(
                response,
                destination,
                metadata,
                need_sha256=True,
                need_git_sha1=False,
            )
        finally:
            response.close()

        assert digest == (len(content), expected_sha256, None)
        assert destination.getvalue() == content

        wrong_metadata = AssetMetadata(
            metadata.name,
            metadata.size,
            "0" * 64,
            None,
        )
        wrong_response = client.send(
            client.build_request("GET", "https://fixture.example/model.onnx"),
            stream=True,
        )
        try:
            wrong_digest = acquisition_io._stream_asset_to_file(
                wrong_response,
                BytesIO(),
                metadata,
                need_sha256=True,
                need_git_sha1=False,
            )
        finally:
            wrong_response.close()
        with pytest.raises(ValueError, match="identity mismatch"):
            acquisition_io._validate_download_digest(wrong_metadata, wrong_digest)


def test_legacy_direct_snapshot_files_do_not_invent_blob_checksums(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Direct legacy snapshot files without a known blob identity are not rehashed."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)
    for name in ASSET_BYTES:
        asset = _snapshot_path(cache_root, REVISION, name)
        content = asset.read_bytes()
        asset.unlink()
        asset.write_bytes(content)
    _install_mock_transport(
        monkeypatch,
        lambda request: httpx.Response(500, request=request),
    )

    def unexpected_hash(*args: object, **kwargs: object) -> object:
        raise AssertionError("direct legacy files have no expected checksum")

    monkeypatch.setattr(cache_fs.hashlib, "sha256", unexpected_hash)
    monkeypatch.setattr(cache_fs.hashlib, "sha1", unexpected_hash)
    sink = _CapturingSink()

    revision = stream_embedding_model_artifacts(None, _settings(cache_root), sink)

    assert revision == REVISION
    assert sink.content_by_name() == ASSET_BYTES


def test_parent_blob_directory_swap_to_outside_symlink_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A transient blobs-parent swap cannot redirect an offline read outside cache."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)
    outside = tmp_path / "outside-blobs"
    outside.mkdir()
    outside_blob = _blob_name("onnx/model.onnx", ASSET_BYTES["onnx/model.onnx"])
    (outside / outside_blob).write_bytes(b"outside-bytes-must-not-be-read")
    requests: list[httpx.Request] = []
    _install_mock_transport(
        monkeypatch,
        lambda request: (
            requests.append(request) or httpx.Response(500, request=request)
        ),
    )
    real_open = cache_fs.os.open
    real_rename = cache_fs.os.rename
    real_symlink = cache_fs.os.symlink
    real_unlink = cache_fs.os.unlink
    injected = False

    def swap_blobs_parent(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal injected
        if path == "blobs" and flags & os.O_DIRECTORY and not injected:
            assert dir_fd is not None
            injected = True
            real_rename(
                "blobs",
                "blobs-held-for-test",
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            real_symlink(str(outside), "blobs", dir_fd=dir_fd)
            try:
                return real_open(path, flags, mode=mode, dir_fd=dir_fd)
            finally:
                real_unlink("blobs", dir_fd=dir_fd)
                real_rename(
                    "blobs-held-for-test",
                    "blobs",
                    src_dir_fd=dir_fd,
                    dst_dir_fd=dir_fd,
                )
        return real_open(path, flags, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(cache_fs.os, "open", swap_blobs_parent)

    with pytest.raises(ValueError):
        _capture_stream(None, _settings(cache_root))

    assert injected is True
    assert not (
        cache_root / "models--intfloat--multilingual-e5-small" / "blobs"
    ).is_symlink()
    assert requests == []


def test_leaf_symlink_swap_is_rejected_before_external_bytes_are_opened(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Every cached leaf open uses no-follow semantics under its held directory fd."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)
    blob_name = _blob_name("onnx/model.onnx", ASSET_BYTES["onnx/model.onnx"])
    model_dir = _model_dir(cache_root)
    blob_dir = model_dir / "blobs"
    outside = tmp_path / "outside-leaf"
    outside.write_bytes(b"external-leaf-bytes")
    requests: list[httpx.Request] = []
    _install_mock_transport(
        monkeypatch,
        lambda request: (
            requests.append(request) or httpx.Response(500, request=request)
        ),
    )
    real_open = cache_fs.os.open
    real_rename = cache_fs.os.rename
    real_symlink = cache_fs.os.symlink
    real_unlink = cache_fs.os.unlink
    injected = False

    def swap_blob_leaf(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal injected
        if path == blob_name and not injected:
            assert dir_fd is not None
            assert flags & os.O_NOFOLLOW
            injected = True
            real_rename(
                blob_name,
                f"{blob_name}-held-for-test",
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            real_symlink(str(outside), blob_name, dir_fd=dir_fd)
            try:
                return real_open(path, flags, mode=mode, dir_fd=dir_fd)
            finally:
                real_unlink(blob_name, dir_fd=dir_fd)
                real_rename(
                    f"{blob_name}-held-for-test",
                    blob_name,
                    src_dir_fd=dir_fd,
                    dst_dir_fd=dir_fd,
                )
        return real_open(path, flags, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(cache_fs.os, "open", swap_blob_leaf)

    with pytest.raises(ValueError):
        _capture_stream(None, _settings(cache_root))

    assert injected is True
    assert (blob_dir / blob_name).read_bytes() == ASSET_BYTES["onnx/model.onnx"]
    assert requests == []


def test_fifo_leaf_swap_uses_nonblocking_open_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A leaf changed to a FIFO is rejected without a blocking open."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION)
    blob_name = _blob_name("onnx/model.onnx", ASSET_BYTES["onnx/model.onnx"])
    blob_dir = _model_dir(cache_root) / "blobs"
    real_open = cache_fs.os.open
    real_rename = cache_fs.os.rename
    real_mkfifo = cache_fs.os.mkfifo
    real_unlink = cache_fs.os.unlink
    injected = False

    def swap_blob_to_fifo(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal injected
        if path == blob_name and not injected:
            assert dir_fd is not None
            assert flags & os.O_NONBLOCK
            injected = True
            real_rename(
                blob_name,
                f"{blob_name}-held-for-test",
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            real_mkfifo(blob_name, mode=0o600, dir_fd=dir_fd)
            try:
                return real_open(path, flags, mode=mode, dir_fd=dir_fd)
            finally:
                real_unlink(blob_name, dir_fd=dir_fd)
                real_rename(
                    f"{blob_name}-held-for-test",
                    blob_name,
                    src_dir_fd=dir_fd,
                    dst_dir_fd=dir_fd,
                )
        return real_open(path, flags, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(cache_fs.os, "open", swap_blob_to_fifo)

    with pytest.raises(ValueError):
        _capture_stream(None, _settings(cache_root))

    assert injected is True
    assert (blob_dir / blob_name).read_bytes() == ASSET_BYTES["onnx/model.onnx"]


def test_cache_root_precedence_is_hf_home_then_argument_then_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The loader preserves all three legacy cache-root precedence branches."""
    hf_home = tmp_path / "hf-home"
    explicit = tmp_path / "explicit-cache"
    fallback = tmp_path / "fallback-cache"
    _write_snapshot(hf_home, REVISION)
    _write_snapshot(explicit, OTHER_REVISION)
    fallback_revision = "c" * 40
    _write_snapshot(fallback, fallback_revision)
    _install_mock_transport(
        monkeypatch,
        lambda request: httpx.Response(500, request=request),
    )

    from_hf_home = _capture_stream(str(explicit), _settings(fallback, hf_home=hf_home))
    from_argument = _capture_stream(str(explicit), _settings(fallback))
    from_settings = _capture_stream(None, _settings(fallback))

    assert from_hf_home.revision == REVISION
    assert from_argument.revision == OTHER_REVISION
    assert from_settings.revision == fallback_revision


def test_empty_hf_home_keeps_legacy_precedence_over_explicit_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An empty HF_HOME remains the current directory and still wins precedence."""
    monkeypatch.chdir(tmp_path)
    _write_snapshot(Path(""), REVISION)
    explicit_cache = tmp_path / "explicit-cache"
    _write_snapshot(explicit_cache, OTHER_REVISION)
    _install_mock_transport(
        monkeypatch,
        lambda request: httpx.Response(500, request=request),
    )

    artifacts = _capture_stream(
        str(explicit_cache),
        _settings(tmp_path / "fallback-cache", hf_home=Path("")),
    )

    assert artifacts.revision == REVISION


@pytest.mark.parametrize("cache_dir", ("~literal-cache", "  literal cache  "))
def test_explicit_cache_paths_remain_literal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cache_dir: str,
) -> None:
    """Explicit cache paths keep tilde and whitespace as literal path components."""
    monkeypatch.chdir(tmp_path)
    _write_snapshot(Path(cache_dir), REVISION)
    _install_mock_transport(
        monkeypatch,
        lambda request: httpx.Response(500, request=request),
    )

    artifacts = _capture_stream(cache_dir, _settings(tmp_path / "fallback"))

    assert artifacts.revision == REVISION


def test_explicit_whitespace_only_cache_argument_remains_rejected(
    tmp_path: Path,
) -> None:
    """The existing explicit cache argument guard rejects whitespace-only input."""
    with pytest.raises(ValueError, match="cache path"):
        _capture_stream("   ", _settings(tmp_path / "fallback"))


def test_new_cache_root_chain_fsyncs_each_parent_before_descending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """New root components are made durable before creating deeper cache entries."""
    root = tmp_path / "chain-one" / "chain-two" / "cache"
    synced_directories: set[tuple[int, int]] = set()
    real_fsync = cache_fs.os.fsync

    def recording_fsync(descriptor: int) -> None:
        entry = os.fstat(descriptor)
        synced_directories.add((entry.st_dev, entry.st_ino))
        real_fsync(descriptor)

    monkeypatch.setattr(cache_fs.os, "fsync", recording_fsync)

    with ArtifactCache(root) as cache:
        cache.directory.ensure_model_directory()

    expected_parents = {
        (path.stat().st_dev, path.stat().st_ino)
        for path in (
            tmp_path,
            tmp_path / "chain-one",
            tmp_path / "chain-one" / "chain-two",
            root,
        )
    }
    assert expected_parents <= synced_directories


def test_root_creation_stops_when_parent_fsync_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A parent durability failure prevents creating later root components."""
    root = tmp_path / "chain-one" / "chain-two" / "cache"
    target = tmp_path.stat()
    target_identity = (target.st_dev, target.st_ino)
    real_fsync = cache_fs.os.fsync

    def failing_parent_fsync(descriptor: int) -> None:
        entry = os.fstat(descriptor)
        if (entry.st_dev, entry.st_ino) == target_identity:
            raise OSError("injected parent directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(cache_fs.os, "fsync", failing_parent_fsync)
    cache = ArtifactCache(root)

    with (
        pytest.raises(OSError, match="injected parent directory fsync failure"),
        cache,
    ):
        cache.directory.ensure_model_directory()

    assert (tmp_path / "chain-one").is_dir()
    assert not (tmp_path / "chain-one" / "chain-two").exists()
    assert not root.exists()


def test_staging_cleanup_closes_fd_and_does_not_mask_primary_error(
    tmp_path: Path,
) -> None:
    """Uncertain staged content is preserved while cleanup keeps the body error primary."""
    cache_root = tmp_path / "cache"
    model_dir = cache_root / MODEL_CACHE_NAME
    stage_path: Path | None = None
    stage_descriptor = -1

    with ArtifactCache(cache_root) as cache:
        cache.directory.ensure_model_directory()
        with (
            pytest.raises(ValueError, match="primary acquisition failure") as failure,
            staging_directory(directory=cache.directory) as staging,
        ):
            stage_path = model_dir / staging._name / "asset-0.part"
            with staging.create_file("asset-0.part") as stream:
                stream.write(b"old")
            stage_descriptor = staging._descriptor
            stage_path.write_bytes(b"new")
            raise ValueError("primary acquisition failure")

    assert stage_path is not None
    assert stage_path.read_bytes() == b"new"
    assert "staging cleanup also failed" in failure.value.__notes__[0]
    with pytest.raises(OSError):
        os.fstat(stage_descriptor)


def test_fresh_cache_resolves_main_once_then_pins_all_asset_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fresh acquisition uses one main metadata result and pins each file to its SHA."""
    cache_root = _cache_root(tmp_path)
    token_path = tmp_path / "token"
    token_path.write_text("hf_synthetic_test_token\n", encoding="utf-8")
    metadata_requests: list[tuple[str, str | None]] = []
    asset_revisions: list[str] = []
    authorization: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization.append(request.headers.get("Authorization"))
        main_path = f"/api/models/{MODEL_ID}/revision/main"
        if request.url.path == main_path:
            metadata_requests.append(
                (request.url.path, request.url.params.get("blobs"))
            )
            return httpx.Response(200, request=request, json=_metadata(REVISION))
        marker = f"/resolve/{REVISION}/"
        if marker in request.url.path:
            asset_revisions.append(REVISION)
            return _response_for_model_request(request, revision=REVISION)
        return httpx.Response(404, request=request)

    _install_mock_transport(monkeypatch, handler)

    artifacts = _capture_stream(
        None,
        _settings(cache_root, token_path=token_path),
    )

    assert artifacts.revision == REVISION
    assert metadata_requests == [(f"/api/models/{MODEL_ID}/revision/main", "true")]
    assert asset_revisions == [REVISION] * len(ASSET_BYTES)
    assert authorization == ["Bearer hf_synthetic_test_token"] * (1 + len(ASSET_BYTES))
    assert (_model_dir(cache_root) / "refs" / "main").read_text(
        encoding="ascii"
    ).strip() == REVISION
    assert all(
        _snapshot_path(cache_root, REVISION, name).read_bytes() == content
        for name, content in ASSET_BYTES.items()
    )


def test_model_info_boundary_ignores_malformed_unselected_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid unrelated files do not enter the fixed-five metadata contract."""
    cache_root = _cache_root(tmp_path)
    model_metadata = _metadata(REVISION)
    siblings = cast(list[dict[str, object]], model_metadata["siblings"])
    siblings.extend(
        (
            {
                "rfilename": "unselected-empty.bin",
                "size": 0,
                "blobId": "not-a-git-blob",
                "lfs": {"sha256": "bad", "size": 0},
            },
            {"size": "malformed", "blob_id": [], "lfs": "malformed"},
        )
    )
    main_path = f"/api/models/{MODEL_ID}/revision/main"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == main_path:
            return httpx.Response(200, request=request, json=model_metadata)
        return _response_for_model_request(request, revision=REVISION)

    _install_mock_transport(monkeypatch, handler)

    captured = _capture_stream(None, _settings(cache_root))

    assert captured.revision == REVISION
    assert captured.sink.content_by_name() == ASSET_BYTES


def test_model_info_uses_only_the_blob_id_wire_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An internal-looking `blob_id` key does not populate the external `blobId`."""
    cache_root = _cache_root(tmp_path)
    model_metadata = _metadata(REVISION)
    siblings = cast(list[dict[str, object]], model_metadata["siblings"])
    config_sibling = next(
        sibling for sibling in siblings if sibling.get("rfilename") == "config.json"
    )
    expected_git_id = config_sibling.pop("blobId")
    config_sibling["blob_id"] = expected_git_id
    main_path = f"/api/models/{MODEL_ID}/revision/main"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == main_path:
            return httpx.Response(200, request=request, json=model_metadata)
        return _response_for_model_request(request, revision=REVISION)

    _install_mock_transport(monkeypatch, handler)

    captured = _capture_stream(None, _settings(cache_root))
    link_target = os.readlink(_snapshot_path(cache_root, REVISION, "config.json"))

    assert captured.revision == REVISION
    assert Path(link_target).name == sha256(ASSET_BYTES["config.json"]).hexdigest()
    assert Path(link_target).name != expected_git_id


@pytest.mark.parametrize(
    "invalidity",
    (
        "missing-asset",
        "duplicate-asset",
        "non-list-siblings",
        "lfs-length-conflict",
        "wrong-type",
        "selected-zero-size",
        "revision",
    ),
)
def test_model_info_json_boundary_rejects_invalid_fixed_asset_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalidity: str,
) -> None:
    """Pydantic validates raw model-info JSON before fixed-asset policy checks."""
    cache_root = _cache_root(tmp_path)
    model_metadata = _metadata(REVISION)
    siblings = cast(list[dict[str, object]], model_metadata["siblings"])
    if invalidity == "missing-asset":
        model_metadata["siblings"] = [
            sibling for sibling in siblings if sibling.get("rfilename") != "config.json"
        ]
    elif invalidity == "duplicate-asset":
        siblings.append(dict(siblings[0]))
    elif invalidity == "non-list-siblings":
        model_metadata["siblings"] = "not-a-list"
    elif invalidity == "lfs-length-conflict":
        onnx = next(
            sibling
            for sibling in siblings
            if sibling.get("rfilename") == "onnx/model.onnx"
        )
        lfs = cast(dict[str, object], onnx["lfs"])
        lfs["size"] = int(lfs["size"]) + 1
    elif invalidity == "wrong-type":
        tokenizer = next(
            sibling
            for sibling in siblings
            if sibling.get("rfilename") == "tokenizer.json"
        )
        tokenizer["size"] = str(tokenizer["size"])
    elif invalidity == "selected-zero-size":
        config = next(
            sibling for sibling in siblings if sibling.get("rfilename") == "config.json"
        )
        config["size"] = 0
    else:
        model_metadata["sha"] = "main"

    main_path = f"/api/models/{MODEL_ID}/revision/main"
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == main_path:
            return httpx.Response(200, request=request, json=model_metadata)
        return httpx.Response(500, request=request)

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(ValueError, match="model metadata"):
        _capture_stream(None, _settings(cache_root))

    assert requests == [main_path]


def test_partial_snapshot_repairs_only_its_pinned_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An existing ref repairs missing files at that revision without resolving main."""
    cache_root = _cache_root(tmp_path)
    missing_asset = "tokenizer_config.json"
    _write_snapshot(cache_root, REVISION, missing=frozenset({missing_asset}))
    metadata_paths: list[str] = []
    downloads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/models/" in request.url.path:
            metadata_paths.append(request.url.path)
        if f"/resolve/{REVISION}/" in request.url.path:
            downloads.append(_client_asset_name(request, REVISION))
        return _response_for_model_request(request, revision=REVISION)

    _install_mock_transport(monkeypatch, handler)

    artifacts = _capture_stream(None, _settings(cache_root))

    assert artifacts.revision == REVISION
    assert metadata_paths == [f"/api/models/{MODEL_ID}/revision/{REVISION}"]
    assert downloads == [missing_asset]
    assert (_model_dir(cache_root) / "refs" / "main").read_text(
        encoding="ascii"
    ).strip() == REVISION


def test_malformed_ref_fails_without_resolving_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Malformed cached ref evidence fails closed without falling back to latest main."""
    cache_root = _cache_root(tmp_path)
    model_dir = _model_dir(cache_root)
    (model_dir / "refs").mkdir(parents=True)
    (model_dir / "refs" / "main").write_text("main\n", encoding="ascii")
    requests: list[httpx.Request] = []
    _install_mock_transport(
        monkeypatch,
        lambda request: (
            requests.append(request) or httpx.Response(500, request=request)
        ),
    )

    with pytest.raises(ValueError, match="reference"):
        _capture_stream(None, _settings(cache_root))

    assert requests == []


def test_snapshot_symlink_cannot_escape_the_configured_model_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Only legitimate snapshot-to-blob symlinks confined to this model cache are read."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION, missing=frozenset(ASSET_BYTES.keys()))
    outside = tmp_path / "outside-tokenizer"
    outside.write_bytes(ASSET_BYTES["tokenizer.json"])
    escaped = _snapshot_path(cache_root, REVISION, "tokenizer.json")
    escaped.parent.mkdir(parents=True, exist_ok=True)
    escaped.symlink_to(outside)
    requests: list[httpx.Request] = []
    _install_mock_transport(
        monkeypatch,
        lambda request: (
            requests.append(request) or httpx.Response(500, request=request)
        ),
    )

    with pytest.raises(ValueError, match="cache"):
        _capture_stream(None, _settings(cache_root))

    assert requests == []


def test_conflicting_cached_blob_is_never_overwritten(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A cached file that disagrees with remote identity fails without replacement."""
    cache_root = _cache_root(tmp_path)
    _write_snapshot(cache_root, REVISION, missing=frozenset(ASSET_BYTES.keys()))
    model_dir = _model_dir(cache_root)
    content = ASSET_BYTES["tokenizer.json"]
    blob = model_dir / "blobs" / _git_blob_id(content)
    blob.write_bytes(b"conflicting existing bytes")
    snapshot_asset = _snapshot_path(cache_root, REVISION, "tokenizer.json")
    snapshot_asset.parent.mkdir(parents=True, exist_ok=True)
    snapshot_asset.symlink_to(os.path.relpath(blob, start=snapshot_asset.parent))
    original = blob.read_bytes()
    _install_mock_transport(
        monkeypatch,
        lambda request: _response_for_model_request(request, revision=REVISION),
    )

    with pytest.raises(ValueError, match="conflict"):
        _capture_stream(None, _settings(cache_root))

    assert blob.read_bytes() == original


def test_failed_download_keeps_ref_and_does_not_publish_staged_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed repair preserves the current ref and publishes none of its staged files."""
    cache_root = _cache_root(tmp_path)
    existing_asset = "config.json"
    _write_snapshot(
        cache_root, REVISION, missing=frozenset(ASSET_BYTES.keys() - {existing_asset})
    )
    model_dir = _model_dir(cache_root)
    ref_path = model_dir / "refs" / "main"
    ref_before = ref_path.read_bytes()
    metadata_path = f"/api/models/{MODEL_ID}/revision/{REVISION}"
    request_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_paths.append(request.url.path)
        if request.url.path == metadata_path:
            return httpx.Response(200, request=request, json=_metadata(REVISION))
        if f"/resolve/{REVISION}/" in request.url.path:
            asset = _client_asset_name(request, REVISION)
            if asset == "tokenizer.json":
                return httpx.Response(503, request=request, content=b"sensitive body")
            return _response_for_model_request(request, revision=REVISION)
        return httpx.Response(404, request=request)

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(ValueError, match="failed") as failure:
        _capture_stream(None, _settings(cache_root))

    assert "sensitive body" not in str(failure.value)
    assert ref_path.read_bytes() == ref_before
    assert all(
        not _snapshot_path(cache_root, REVISION, asset).exists()
        for asset in ASSET_BYTES
        if asset != existing_asset
    )
    assert not (
        model_dir / "blobs" / _git_blob_id(ASSET_BYTES["tokenizer.json"])
    ).exists()
    assert any(path == metadata_path for path in request_paths)


@pytest.mark.parametrize(
    ("body", "model_metadata", "message"),
    (
        (
            b"short body",
            _metadata(REVISION),
            "length",
        ),
        (
            ASSET_BYTES["onnx/model.onnx"],
            _metadata(
                REVISION,
                lfs_digest_override="0" * 64,
            ),
            "identity",
        ),
        (
            ASSET_BYTES["tokenizer.json"],
            _metadata(REVISION, size_delta=1),
            "length",
        ),
    ),
)
def test_length_or_hash_mismatch_fails_before_ref_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    body: bytes,
    model_metadata: dict[str, object],
    message: str,
) -> None:
    """Declared lengths and available LFS/Git identities are checked before publication."""
    cache_root = _cache_root(tmp_path)
    model_dir = _model_dir(cache_root)
    main_path = f"/api/models/{MODEL_ID}/revision/main"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == main_path:
            return httpx.Response(200, request=request, json=model_metadata)
        asset = _client_asset_name(request, REVISION)
        if asset == "onnx/model.onnx":
            return httpx.Response(200, request=request, content=body)
        return _response_for_model_request(request, revision=REVISION)

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(ValueError, match=message):
        _capture_stream(None, _settings(cache_root))

    assert not (model_dir / "refs" / "main").exists()
    assert not (model_dir / "snapshots" / REVISION).exists()


def test_cross_origin_redirect_strips_token_and_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bearer credentials stay on the configured origin and failures hide URL/token data."""
    cache_root = _cache_root(tmp_path)
    token = "hf_only_for_this_test"
    token_path = tmp_path / "token"
    token_path.write_text(token, encoding="utf-8")
    hf_authorization: list[str | None] = []
    cdn_authorization: list[str | None] = []
    main_path = f"/api/models/{MODEL_ID}/revision/main"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "huggingface.co":
            hf_authorization.append(request.headers.get("Authorization"))
            if request.url.path == main_path:
                return httpx.Response(200, request=request, json=_metadata(REVISION))
            if f"/resolve/{REVISION}/" in request.url.path:
                asset = _client_asset_name(request, REVISION)
                return httpx.Response(
                    302,
                    request=request,
                    headers={"Location": f"https://cdn.example.test/{asset}"},
                )
        if request.url.host == "cdn.example.test":
            cdn_authorization.append(request.headers.get("Authorization"))
            asset = request.url.path.removeprefix("/")
            if asset == "tokenizer.json":
                return httpx.Response(
                    503,
                    request=request,
                    content=f"failed {token} https://cdn.example.test/{asset}".encode(),
                )
            return httpx.Response(200, request=request, content=ASSET_BYTES[asset])
        return httpx.Response(404, request=request)

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(ValueError) as failure:
        _capture_stream(
            None,
            _settings(cache_root, token_path=token_path),
        )

    assert token not in str(failure.value)
    assert "cdn.example.test" not in str(failure.value)
    assert all(value == f"Bearer {token}" for value in hf_authorization)
    assert cdn_authorization and all(value is None for value in cdn_authorization)


def test_authenticated_https_redirect_cannot_downgrade_to_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A token-authenticated HTTPS request rejects an HTTP redirect before following it."""
    cache_root = _cache_root(tmp_path)
    token_path = tmp_path / "token"
    token_path.write_text("hf_synthetic_test_token", encoding="utf-8")
    requests: list[httpx.Request] = []
    main_path = f"/api/models/{MODEL_ID}/revision/main"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == main_path:
            return httpx.Response(
                302,
                request=request,
                headers={
                    "Location": f"http://huggingface.co{main_path}",
                },
            )
        return httpx.Response(200, request=request, json=_metadata(REVISION))

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(ValueError, match="downgrade"):
        _capture_stream(
            None,
            _settings(cache_root, token_path=token_path),
        )

    assert len(requests) == 1
    assert requests[0].url.scheme == "https"


def test_concurrent_loaders_publish_one_complete_pinned_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Concurrent cold-cache callers converge on one complete immutable snapshot."""
    cache_root = _cache_root(tmp_path)
    metadata_path = f"/api/models/{MODEL_ID}/revision/main"
    metadata_requests = 0
    counter_lock = threading.Lock()
    begin = threading.Barrier(4)
    download_started = threading.Event()
    release_download = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal metadata_requests
        if request.url.path == metadata_path:
            with counter_lock:
                metadata_requests += 1
            return httpx.Response(200, request=request, json=_metadata(REVISION))
        if f"/resolve/{REVISION}/" in request.url.path:
            if not download_started.is_set():
                download_started.set()
                assert release_download.wait(timeout=10)
            return _response_for_model_request(request, revision=REVISION)
        return httpx.Response(404, request=request)

    _install_mock_transport(monkeypatch, handler)

    def load_after_barrier() -> _CapturedArtifacts:
        begin.wait(timeout=10)
        return _capture_stream(None, _settings(cache_root))

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(load_after_barrier) for _ in range(4)]
        assert download_started.wait(timeout=10)
        release_download.set()
        results = [future.result(timeout=20) for future in futures]

    assert metadata_requests == 1
    assert all(result.revision == REVISION for result in results)
    assert all(
        _snapshot_path(cache_root, REVISION, name).read_bytes() == content
        for name, content in ASSET_BYTES.items()
    )
