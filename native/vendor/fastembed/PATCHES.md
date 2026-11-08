# FastEmbed 5.17.4 local model-lifetime patch

This is the existing, pinned FastEmbed dependency, not a new inference implementation.
`UPSTREAM.json` records the verified crates.io archive checksum, upstream VCS metadata,
and file hashes. The upstream license is retained in `LICENSE`.

Five files differ from the selected upstream files:

- `src/text_embedding/impl.rs` separates owned ONNX session preparation from
  tokenizer initialization. Generic owned input is released after the ORT commit
  returns. The existing user-defined constructor delegates to the same
  implementation and preserves its external-initializer path.
- `src/text_embedding/init.rs` defines the opaque pending session. `src/lib.rs`
  reexports it. It exposes no inference until consuming `finish(tokenizer_files)`.
- The same files add a caller-owned CPU FLOAT initializer whose checked,
  initialized backing satisfies ORT's public registration precondition. The
  staged constructor accepts these tensor values while preserving the existing
  file-buffer constructor. `Cargo.toml` reuses the already-locked `zerocopy`
  package for initialized allocation and safe byte access; no package/version
  is added to the dependency set.
- In `src/common.rs`, padding and truncation mutate the already-owned tokenizer
  in place. The redundant `.clone()` of that configured tokenizer is removed.
Weights, tokenizer, pooling, normalization and execution options remain unchanged.
Alexandria's pure core validates original ONNX bytes and creates a transient
representation for selected FLOAT initializers. Exact tensor registrations are
validated before committing that representation. This avoids reconstructing the
large protobuf raw-data payload; ORT still copies caller-backed tensors, and the
Rust backing guard remains retained by the session. This is not a zero-copy claim.
The original ONNX input is released before commit/tokenizer transfer. No native
filesystem or network path is enabled.

The original constructor retained roughly 470 MB of serialized ONNX data while
allocating tokenizer state, and tokenization setup then cloned the entire owned
tokenizer. These changes remove unnecessary overlap and duplication. Numerical
parity and same-condition peak-RSS measurements are required before acceptance.

To reproduce, use the FastEmbed 5.17.4 crate archive matching `UPSTREAM.json`, retain
`Cargo.toml`, `Cargo.toml.orig`, `LICENSE`, `README.md`, `.cargo_vcs_info.json`, `src/`
and `tests/`, then apply the changes recorded in `UPSTREAM.json` under `patches`.
The remaining upstream development files and Cargo registry bookkeeping
are not needed by this workspace. `native/Cargo.lock` is the dependency lock authority;
this crate is excluded from workspace members and is selected by `[patch.crates-io]`.

Remove this local patch when an adopted upstream release includes an equivalent
lifetime fix, after rerunning the same behavior and performance checks. Never patch
the shared Cargo registry cache.

Canonical native CI runs the focused `owned_initializer_` SDK tests, including
actual public ORT registration, without loading a cached model.
