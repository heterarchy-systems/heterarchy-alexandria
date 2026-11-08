//! Synchronized streamed transfer of the fixed multilingual-E5 model assets.

use std::sync::{Arc, Mutex};

use heterarchy_alexandria_model_buffer::MutableModelBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use super::{MultilingualE5Session, initialize_session, prepare_session};

const ASSET_NAMES: [&str; 5] = [
    "onnx/model.onnx",
    "tokenizer.json",
    "config.json",
    "special_tokens_map.json",
    "tokenizer_config.json",
];
const MAX_EMBEDDING_THREADS: usize = 4_096;

/// Create the one-shot native builder for a fixed multilingual-E5 runtime.
///
/// # Errors
///
/// Returns a sanitized configuration error when the requested thread count is unsupported.
pub(crate) fn create_multilingual_e5_runtime_builder(
    threads: usize,
) -> Result<MultilingualE5RuntimeBuilder, String> {
    validate_threads(threads)?;
    Ok(MultilingualE5RuntimeBuilder {
        state: Arc::new(Mutex::new(Some(BuilderState::new(threads)))),
    })
}

/// One-shot receiver for the five fixed multilingual-E5 model assets.
#[pyclass(module = "heterarchy_alexandria_native")]
pub(crate) struct MultilingualE5RuntimeBuilder {
    state: Arc<Mutex<Option<BuilderState>>>,
}

#[pymethods]
impl MultilingualE5RuntimeBuilder {
    /// Begin the next fixed-name model asset with its declared byte length.
    fn begin_asset(&self, python: Python<'_>, name: &str, size: usize) -> PyResult<()> {
        let state = Arc::clone(&self.state);
        python
            .detach(move || {
                apply_transfer_operation(&state, |builder| builder.begin_asset(name, size))
            })
            .map_err(PyValueError::new_err)
    }

    /// Append one immutable chunk to the currently open model asset.
    fn write_chunk(&self, python: Python<'_>, chunk: &[u8]) -> PyResult<()> {
        let state = Arc::clone(&self.state);
        python
            .detach(move || apply_transfer_operation(&state, |builder| builder.write_chunk(chunk)))
            .map_err(PyValueError::new_err)
    }

    /// Mark one asset complete only after the Python reader validated its digest and fences.
    fn asset_verified(&self, python: Python<'_>, name: &str) -> PyResult<()> {
        let name = name.to_owned();
        let state = Arc::clone(&self.state);
        python
            .detach(move || {
                apply_transfer_operation(&state, |builder| builder.asset_verified(&name))
            })
            .map_err(PyValueError::new_err)
    }

    /// Consume the completed transfer and initialize its provider-owned native session.
    fn finish(&self, python: Python<'_>) -> PyResult<Py<MultilingualE5Session>> {
        let state = Arc::clone(&self.state);
        let session = python
            .detach(move || take_builder_state(&state).and_then(finish_state))
            .map_err(PyValueError::new_err)?;
        Py::new(python, session)
    }

    /// Drop pending native buffers without allowing cleanup to mask an active Python error.
    fn close(&self, python: Python<'_>) {
        let state = Arc::clone(&self.state);
        python.detach(move || close_builder_state(&state));
    }
}

struct BuilderState {
    threads: usize,
    next_asset_index: usize,
    current_asset_length: Option<usize>,
    current_asset_written: usize,
    awaiting_asset_verification: bool,
    onnx: Option<MutableModelBuffer>,
    assets: [Vec<u8>; 4],
    prepared: Option<fastembed::PreparedTextEmbedding>,
}

impl BuilderState {
    fn new(threads: usize) -> Self {
        Self {
            threads,
            next_asset_index: 0,
            current_asset_length: None,
            current_asset_written: 0,
            awaiting_asset_verification: false,
            onnx: None,
            assets: std::array::from_fn(|_| Vec::new()),
            prepared: None,
        }
    }

    fn begin_asset(&mut self, name: &str, declared_length: usize) -> Result<(), String> {
        if self.current_asset_length.is_some() || self.awaiting_asset_verification {
            return Err(transfer_error("previous asset is incomplete"));
        }
        let Some(expected_name) = ASSET_NAMES.get(self.next_asset_index) else {
            return Err(transfer_error("all model assets are already verified"));
        };
        if name != *expected_name {
            return Err(transfer_error("asset name or order is invalid"));
        }
        if self.next_asset_index == 0 {
            self.onnx = Some(
                MutableModelBuffer::new(declared_length)
                    .map_err(|_| transfer_error("cannot allocate the ONNX model buffer"))?,
            );
        } else {
            let asset_index = self.next_asset_index - 1;
            let Some(asset) = self.assets.get_mut(asset_index) else {
                return Err(transfer_error("asset transfer state is invalid"));
            };
            asset
                .try_reserve_exact(declared_length)
                .map_err(|_| transfer_error("cannot reserve declared asset length"))?;
        }
        self.current_asset_length = Some(declared_length);
        self.current_asset_written = 0;
        if declared_length == 0 {
            self.current_asset_length = None;
            self.awaiting_asset_verification = true;
        }
        Ok(())
    }

    fn write_chunk(&mut self, chunk: &[u8]) -> Result<(), String> {
        let Some(expected_length) = self.current_asset_length else {
            return Err(transfer_error("no asset is open for writing"));
        };
        let new_length =
            checked_chunk_length(self.current_asset_written, chunk.len(), expected_length)?;
        if self.next_asset_index == 0 {
            let Some(onnx) = self.onnx.as_mut() else {
                return Err(transfer_error("ONNX model buffer is unavailable"));
            };
            onnx.as_mut()[self.current_asset_written..new_length].copy_from_slice(chunk);
        } else {
            let asset_index = self.next_asset_index - 1;
            let Some(asset) = self.assets.get_mut(asset_index) else {
                return Err(transfer_error("asset transfer state is invalid"));
            };
            asset.extend_from_slice(chunk);
        }
        self.current_asset_written = new_length;
        if new_length == expected_length {
            self.current_asset_length = None;
            self.current_asset_written = 0;
            self.awaiting_asset_verification = true;
        }
        Ok(())
    }

    fn asset_verified(&mut self, name: &str) -> Result<(), String> {
        validate_asset_verification(
            self.next_asset_index,
            self.awaiting_asset_verification && self.current_asset_length.is_none(),
            name,
        )?;
        if self.next_asset_index == 0 {
            let Some(onnx) = self.onnx.take() else {
                return Err(transfer_error("ONNX model buffer is unavailable"));
            };
            let onnx = onnx
                .freeze()
                .map_err(|_| transfer_error("cannot seal the ONNX model buffer"))?;
            self.prepared = Some(prepare_session(onnx, self.threads)?);
        }
        self.awaiting_asset_verification = false;
        self.next_asset_index += 1;
        Ok(())
    }

    fn into_complete_assets(self) -> Result<CompletedAssets, String> {
        if self.current_asset_length.is_some()
            || self.awaiting_asset_verification
            || self.next_asset_index != ASSET_NAMES.len()
        {
            return Err(transfer_error(
                "all five model assets must be verified before finish",
            ));
        }
        let [tokenizer, config, special_tokens_map, tokenizer_config] = self.assets;
        let Some(prepared) = self.prepared else {
            return Err(transfer_error("prepared ONNX session is unavailable"));
        };
        Ok(CompletedAssets {
            prepared,
            tokenizer,
            config,
            special_tokens_map,
            tokenizer_config,
        })
    }
}

struct CompletedAssets {
    prepared: fastembed::PreparedTextEmbedding,
    tokenizer: Vec<u8>,
    config: Vec<u8>,
    special_tokens_map: Vec<u8>,
    tokenizer_config: Vec<u8>,
}

fn validate_asset_verification(
    next_asset_index: usize,
    awaiting_asset_verification: bool,
    name: &str,
) -> Result<(), String> {
    if !awaiting_asset_verification {
        return Err(transfer_error("asset has not completed transfer"));
    }
    let Some(expected_name) = ASSET_NAMES.get(next_asset_index) else {
        return Err(transfer_error("all model assets are already verified"));
    };
    if name != *expected_name {
        return Err(transfer_error("asset verification order is invalid"));
    }
    Ok(())
}

fn validate_threads(threads: usize) -> Result<(), String> {
    if threads == 0 || threads > MAX_EMBEDDING_THREADS {
        return Err(format!(
            "NATIVE_EMBEDDING_RUNTIME_ERROR: threads must be between 1 and {MAX_EMBEDDING_THREADS}"
        ));
    }
    Ok(())
}

fn checked_chunk_length(current: usize, chunk: usize, expected: usize) -> Result<usize, String> {
    let new_length = current
        .checked_add(chunk)
        .ok_or_else(|| transfer_error("asset byte count overflow"))?;
    if new_length > expected {
        return Err(transfer_error("asset chunk exceeds declared length"));
    }
    Ok(new_length)
}

fn apply_transfer_operation(
    state: &Mutex<Option<BuilderState>>,
    operation: impl FnOnce(&mut BuilderState) -> Result<(), String>,
) -> Result<(), String> {
    let mut guard = match state.lock() {
        Ok(guard) => guard,
        Err(poisoned) => {
            let mut guard = poisoned.into_inner();
            let pending = guard.take();
            drop(guard);
            drop(pending);
            return Err(transfer_error("builder state lock was poisoned"));
        }
    };
    let Some(builder) = guard.as_mut() else {
        return Err(transfer_error("builder has already been consumed"));
    };
    match operation(builder) {
        Ok(()) => Ok(()),
        Err(error) => {
            let pending = guard.take();
            drop(guard);
            drop(pending);
            Err(error)
        }
    }
}

fn take_builder_state(state: &Mutex<Option<BuilderState>>) -> Result<BuilderState, String> {
    let mut guard = match state.lock() {
        Ok(guard) => guard,
        Err(poisoned) => {
            let mut guard = poisoned.into_inner();
            let pending = guard.take();
            drop(guard);
            drop(pending);
            return Err(transfer_error("builder state lock was poisoned"));
        }
    };
    guard
        .take()
        .ok_or_else(|| transfer_error("builder has already been consumed"))
}

fn close_builder_state(state: &Mutex<Option<BuilderState>>) {
    let pending = match state.lock() {
        Ok(mut guard) => guard.take(),
        Err(poisoned) => poisoned.into_inner().take(),
    };
    drop(pending);
}

fn finish_state(state: BuilderState) -> Result<MultilingualE5Session, String> {
    let assets = state.into_complete_assets()?;
    initialize_session(
        assets.prepared,
        assets.tokenizer,
        assets.config,
        assets.special_tokens_map,
        assets.tokenizer_config,
    )
}

fn transfer_error(message: &str) -> String {
    format!("NATIVE_EMBEDDING_RUNTIME_TRANSFER_ERROR: {message}")
}

#[cfg(test)]
mod tests {
    use super::{
        ASSET_NAMES, BuilderState, apply_transfer_operation, close_builder_state,
        validate_asset_verification,
    };
    use std::sync::{Arc, Barrier, Mutex};
    use std::thread;

    fn is_closed(state: &Mutex<Option<BuilderState>>) -> bool {
        match state.lock() {
            Ok(guard) => guard.is_none(),
            Err(poisoned) => poisoned.into_inner().is_none(),
        }
    }

    fn state_with_small_asset(index: usize, name: &str, bytes: &[u8]) -> BuilderState {
        let mut state = BuilderState::new(4);
        state.next_asset_index = index;
        if let Err(error) = state.begin_asset(name, bytes.len()) {
            unreachable!("fixed small fixture asset must begin: {error}");
        }
        if let Err(error) = state.write_chunk(bytes) {
            unreachable!("fixed fixture chunk must be accepted: {error}");
        }
        state
    }

    #[test]
    fn asset_verification_rejects_incomplete_wrong_and_repeated_markers() {
        assert!(validate_asset_verification(0, false, ASSET_NAMES[0]).is_err());
        assert!(validate_asset_verification(0, true, ASSET_NAMES[1]).is_err());
        assert!(validate_asset_verification(ASSET_NAMES.len(), true, "extra").is_err());
        assert!(validate_asset_verification(2, true, ASSET_NAMES[2]).is_ok());
        assert!(validate_asset_verification(3, false, ASSET_NAMES[2]).is_err());
    }

    #[test]
    fn premature_asset_verification_consumes_builder_and_pending_buffers() {
        let mut builder = BuilderState::new(4);
        builder.next_asset_index = 1;
        assert!(builder.begin_asset(ASSET_NAMES[1], 9).is_ok());
        assert!(builder.write_chunk(b"token").is_ok());
        let shared_state = Arc::new(Mutex::new(Some(builder)));
        let result =
            apply_transfer_operation(&shared_state, |state| state.asset_verified(ASSET_NAMES[1]));

        assert!(result.is_err());
        assert!(is_closed(&shared_state));
    }

    #[test]
    fn repeated_asset_verification_consumes_builder() {
        let shared_state = Arc::new(Mutex::new(Some(state_with_small_asset(
            1,
            ASSET_NAMES[1],
            b"tokenizer",
        ))));
        let first =
            apply_transfer_operation(&shared_state, |state| state.asset_verified(ASSET_NAMES[1]));
        assert!(first.is_ok());

        let repeated =
            apply_transfer_operation(&shared_state, |state| state.asset_verified(ASSET_NAMES[1]));
        assert!(repeated.is_err());
        assert!(is_closed(&shared_state));
    }

    #[test]
    fn invalid_onnx_is_rejected_at_its_verified_boundary_and_consumes_builder() {
        let shared_state = Arc::new(Mutex::new(Some(BuilderState::new(4))));
        assert!(
            apply_transfer_operation(&shared_state, |state| {
                state.begin_asset(ASSET_NAMES[0], b"not-an-onnx".len())
            })
            .is_ok()
        );
        assert!(
            apply_transfer_operation(&shared_state, |state| { state.write_chunk(b"not-an-onnx") })
                .is_ok()
        );

        let result =
            apply_transfer_operation(&shared_state, |state| state.asset_verified(ASSET_NAMES[0]));
        assert!(result.is_err());
        assert!(is_closed(&shared_state));
    }

    #[test]
    fn wrong_asset_order_consumes_and_drops_builder() {
        let shared_state = Arc::new(Mutex::new(Some(BuilderState::new(4))));
        let result = apply_transfer_operation(&shared_state, |state| {
            state.begin_asset("tokenizer.json", 2)
        });

        assert!(result.is_err());
        assert!(is_closed(&shared_state));
    }

    #[test]
    fn overlong_chunk_consumes_and_drops_builder() {
        let mut builder = BuilderState::new(4);
        builder.next_asset_index = 1;
        assert!(builder.begin_asset(ASSET_NAMES[1], 2).is_ok());
        assert!(builder.write_chunk(b"o").is_ok());
        let shared_state = Arc::new(Mutex::new(Some(builder)));
        let result = apply_transfer_operation(&shared_state, |state| state.write_chunk(b"extra"));

        assert!(result.is_err());
        assert!(is_closed(&shared_state));
    }

    #[test]
    fn chunk_lengths_reject_overrun_and_arithmetic_overflow() {
        assert_eq!(super::checked_chunk_length(2, 1, 3), Ok(3));
        assert!(super::checked_chunk_length(2, 2, 3).is_err());
        assert!(super::checked_chunk_length(usize::MAX, 1, usize::MAX).is_err());
    }

    #[test]
    fn unallocatable_onnx_length_consumes_builder() {
        let shared_state = Arc::new(Mutex::new(Some(BuilderState::new(4))));
        let result = apply_transfer_operation(&shared_state, |state| {
            state.begin_asset(ASSET_NAMES[0], usize::MAX)
        });

        assert!(result.is_err());
        assert!(is_closed(&shared_state));
    }

    #[test]
    fn concurrent_close_waits_for_verified_asset_transition() {
        let state = Arc::new(Mutex::new(Some(state_with_small_asset(
            1,
            ASSET_NAMES[1],
            b"tokenizer",
        ))));
        let reached_close = Arc::new(Barrier::new(2));
        let closer_state = Arc::clone(&state);
        let closer_barrier = Arc::clone(&reached_close);
        let closer = thread::spawn(move || {
            closer_barrier.wait();
            close_builder_state(&closer_state);
        });

        let mut guard = match state.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        reached_close.wait();
        let Some(builder) = guard.as_mut() else {
            unreachable!("builder remains owned during verified-asset transition");
        };
        assert!(builder.asset_verified(ASSET_NAMES[1]).is_ok());
        drop(guard);
        assert!(closer.join().is_ok());
        assert!(is_closed(&state));
    }

    #[test]
    fn close_is_idempotent_and_drops_pending_assets() {
        let mut builder = BuilderState::new(4);
        if let Err(error) = builder.begin_asset(ASSET_NAMES[0], 4) {
            unreachable!("first fixed asset must begin: {error}");
        }
        if let Err(error) = builder.write_chunk(b"ab") {
            unreachable!("partial initial ONNX chunk must be accepted: {error}");
        }
        let shared_state = Mutex::new(Some(builder));

        close_builder_state(&shared_state);
        close_builder_state(&shared_state);

        assert!(is_closed(&shared_state));
    }
}
