//! Strict wire for the deterministic knowledge compile-plan authority.

use heterarchy_alexandria_core::compile_plan::{
    CompilePolicy, CurrentSourceSnapshot, PreviousCompilationSnapshot, compile_plan,
};
use serde::Deserialize;

const COMPILE_PLAN_CONTRACT_VERSION: u16 = 1;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CompilePlanRequestWire {
    contract_version: u16,
    policy: CompilePolicy,
    current: CurrentSourceSnapshot,
    previous: PreviousCompilationSnapshot,
}

/// Compile one deterministic plan for the submitted snapshots.
///
/// # Errors
///
/// Returns a stable machine-readable error when the wire contract or the
/// compiled inputs are invalid.
pub(crate) fn compile_plan_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let request: CompilePlanRequestWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_COMPILE_PLAN_INPUT_ERROR: {error}"))?;
    if request.contract_version != COMPILE_PLAN_CONTRACT_VERSION {
        return Err(format!(
            "NATIVE_COMPILE_PLAN_CONTRACT_ERROR: expected contract version {COMPILE_PLAN_CONTRACT_VERSION}, found {}",
            request.contract_version
        ));
    }
    let plan = compile_plan(&request.current, &request.previous, &request.policy)
        .map_err(|error| format!("NATIVE_COMPILE_PLAN_INVARIANT_ERROR: {error}"))?;
    serde_json::to_vec(&plan).map_err(|error| format!("NATIVE_COMPILE_PLAN_OUTPUT_ERROR: {error}"))
}

use heterarchy_alexandria_core::compile_plan::{
    DiagnosticEdgeInput, DiagnosticNoteInput, resolve_diagnostic_targets,
};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ResolveTargetsRequestWire {
    contract_version: u16,
    notes: Vec<DiagnosticNoteInput>,
    edges: Vec<DiagnosticEdgeInput>,
}

/// Resolve cached edge targets through the single graph resolution authority.
///
/// # Errors
///
/// Returns a stable machine-readable error when the wire contract is invalid.
pub(crate) fn resolve_note_targets_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let request: ResolveTargetsRequestWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_TARGET_RESOLUTION_INPUT_ERROR: {error}"))?;
    if request.contract_version != COMPILE_PLAN_CONTRACT_VERSION {
        return Err(format!(
            "NATIVE_TARGET_RESOLUTION_CONTRACT_ERROR: expected contract version {COMPILE_PLAN_CONTRACT_VERSION}, found {}",
            request.contract_version
        ));
    }
    serde_json::to_vec(&resolve_diagnostic_targets(&request.notes, &request.edges))
        .map_err(|error| format!("NATIVE_TARGET_RESOLUTION_OUTPUT_ERROR: {error}"))
}
