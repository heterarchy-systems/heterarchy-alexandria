use heterarchy_alexandria_core::context_reindex_manifest::{
    CONTEXT_REINDEX_MANIFEST_VERSION, ContextReindexIdentity, ContextReindexManifestCandidate,
    validate_context_reindex_manifest,
};
use serde::Deserialize;
use serde_json::Value;

const GOLDEN_CORPUS: &str = include_str!("../../../golden/context_reindex_manifest.v1.json");

#[derive(Debug, Deserialize)]
struct Corpus {
    contract_version: u16,
    manifest_version: u16,
    cases: Vec<Case>,
}

#[derive(Debug, Deserialize)]
struct Case {
    name: String,
    candidates: Vec<CandidateWire>,
    expected: Value,
}

#[derive(Debug, Deserialize)]
struct CandidateWire {
    note_id: String,
    relative_path: String,
    canonical_relative_path: String,
    alexandria_type: String,
    content_hash: String,
    #[serde(default)]
    scope: Option<String>,
    #[serde(default)]
    project: Option<String>,
    #[serde(default)]
    workspace_id: Option<String>,
    #[serde(default)]
    agent_id: Option<String>,
    #[serde(default)]
    user_id: Option<String>,
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    supersedes_context_id: Option<Value>,
    #[serde(default)]
    superseded_by_context_id: Option<Value>,
}

#[test]
fn context_reindex_manifest_matches_the_frozen_python_oracle() {
    let corpus: Corpus = match serde_json::from_str(GOLDEN_CORPUS) {
        Ok(value) => value,
        Err(error) => unreachable!("golden Context reindex corpus must be valid JSON: {error}"),
    };
    assert_eq!(corpus.contract_version, 1);
    assert_eq!(corpus.manifest_version, CONTEXT_REINDEX_MANIFEST_VERSION);
    assert!(corpus.cases.len() >= 16);

    for case in corpus.cases {
        let candidates = case
            .candidates
            .into_iter()
            .map(candidate_from_wire)
            .collect::<Vec<_>>();
        let actual = match serde_json::to_value(validate_context_reindex_manifest(&candidates)) {
            Ok(value) => value,
            Err(error) => unreachable!("{}: result serialization failed: {error}", case.name),
        };
        assert_eq!(actual, case.expected, "{}", case.name);
    }
}

fn candidate_from_wire(wire: CandidateWire) -> ContextReindexManifestCandidate {
    ContextReindexManifestCandidate {
        note_id: wire.note_id,
        relative_path: wire.relative_path,
        canonical_relative_path: wire.canonical_relative_path,
        is_context: wire.alexandria_type == "context",
        identity: ContextReindexIdentity {
            scope: wire.scope,
            project: wire.project,
            workspace_id: wire.workspace_id,
            agent_id: wire.agent_id,
            user_id: wire.user_id,
            session_id: wire.session_id,
            content_hash: Some(wire.content_hash),
        },
        supersedes_context_id: json_text(wire.supersedes_context_id),
        superseded_by_context_id: json_text(wire.superseded_by_context_id),
    }
}

fn json_text(value: Option<Value>) -> Option<String> {
    match value {
        Some(Value::String(text)) => Some(text),
        _ => None,
    }
}
