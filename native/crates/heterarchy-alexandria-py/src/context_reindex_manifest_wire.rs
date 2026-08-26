//! Strict JSON wire conversion for deterministic Context reindex-manifest validation.

use heterarchy_alexandria_core::context_reindex_manifest::{
    CONTEXT_REINDEX_MANIFEST_VERSION, ContextReindexIdentity, ContextReindexManifestCandidate,
    validate_context_reindex_manifest,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ContextReindexManifestEnvelopeWire {
    contract_version: u16,
    manifest_version: u16,
    candidates: Vec<ContextReindexManifestCandidateWire>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ContextReindexManifestCandidateWire {
    note_id: String,
    relative_path: String,
    canonical_relative_path: String,
    is_context: bool,
    scope: Option<String>,
    project: Option<String>,
    workspace_id: Option<String>,
    agent_id: Option<String>,
    user_id: Option<String>,
    session_id: Option<String>,
    content_hash: Option<String>,
    supersedes_context_id: Option<String>,
    superseded_by_context_id: Option<String>,
}

pub(crate) fn compute_context_reindex_manifest_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: ContextReindexManifestEnvelopeWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_CONTEXT_REINDEX_MANIFEST_INPUT_ERROR: {error}"))?;
    crate::validate_contract_version(
        wire.contract_version,
        "NATIVE_CONTEXT_REINDEX_MANIFEST_CONTRACT_ERROR",
    )?;
    if wire.manifest_version != CONTEXT_REINDEX_MANIFEST_VERSION {
        return Err(format!(
            "NATIVE_CONTEXT_REINDEX_MANIFEST_CONTRACT_ERROR: expected manifest version {CONTEXT_REINDEX_MANIFEST_VERSION}, found {}",
            wire.manifest_version
        ));
    }
    let candidates = wire
        .candidates
        .into_iter()
        .map(candidate_from_wire)
        .collect::<Vec<_>>();
    serde_json::to_vec(&validate_context_reindex_manifest(&candidates))
        .map_err(|error| format!("NATIVE_CONTEXT_REINDEX_MANIFEST_OUTPUT_ERROR: {error}"))
}

fn candidate_from_wire(
    wire: ContextReindexManifestCandidateWire,
) -> ContextReindexManifestCandidate {
    ContextReindexManifestCandidate {
        note_id: wire.note_id,
        relative_path: wire.relative_path,
        canonical_relative_path: wire.canonical_relative_path,
        is_context: wire.is_context,
        identity: ContextReindexIdentity {
            scope: wire.scope,
            project: wire.project,
            workspace_id: wire.workspace_id,
            agent_id: wire.agent_id,
            user_id: wire.user_id,
            session_id: wire.session_id,
            content_hash: wire.content_hash,
        },
        supersedes_context_id: wire.supersedes_context_id,
        superseded_by_context_id: wire.superseded_by_context_id,
    }
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::compute_context_reindex_manifest_payload;

    #[test]
    fn adapter_runs_one_coarse_manifest_validation_request() {
        let payload = br#"{
            "contract_version":1,
            "manifest_version":1,
            "candidates":[
                {
                    "note_id":"ctx-a",
                    "relative_path":"Contexts/A.md",
                    "canonical_relative_path":"Contexts/A.md",
                    "is_context":true,
                    "scope":"GLOBAL",
                    "project":null,
                    "workspace_id":null,
                    "agent_id":null,
                    "user_id":null,
                    "session_id":null,
                    "content_hash":"hash-a",
                    "supersedes_context_id":null,
                    "superseded_by_context_id":null
                }
            ]
        }"#;
        let encoded = match compute_context_reindex_manifest_payload(payload) {
            Ok(value) => value,
            Err(error) => unreachable!("valid manifest payload failed: {error}"),
        };
        let decoded: Value = match serde_json::from_slice(&encoded) {
            Ok(value) => value,
            Err(error) => unreachable!("manifest adapter emitted invalid JSON: {error}"),
        };
        assert_eq!(decoded["accepted_indices"], serde_json::json!([0]));
        assert_eq!(decoded["issues"], serde_json::json!([]));
    }

    #[test]
    fn adapter_rejects_unknown_manifest_versions_and_fields() {
        let version_payload = br#"{
            "contract_version":1,
            "manifest_version":2,
            "candidates":[]
        }"#;
        let Err(version_error) = compute_context_reindex_manifest_payload(version_payload) else {
            unreachable!("unknown manifest version must fail");
        };
        assert!(version_error.contains("expected manifest version 1, found 2"));

        let field_payload = br#"{
            "contract_version":1,
            "manifest_version":1,
            "candidates":[],
            "extra":true
        }"#;
        let Err(field_error) = compute_context_reindex_manifest_payload(field_payload) else {
            unreachable!("unknown manifest field must fail");
        };
        assert!(field_error.contains("unknown field"));
    }
}
