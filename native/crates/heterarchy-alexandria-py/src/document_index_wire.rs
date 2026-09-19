//! Coarse Obsidian document-index compute wire.
//!
//! The Python boundary submits already-read Markdown. Rust performs deterministic
//! document analysis, title fallback, search chunking, and SHA-256 hashing in one
//! FFI call. Python retains filesystem, note-type, relation-policy, and persistence
//! authority.

use std::path::Path;

use heterarchy_alexandria_core::ComputeContractVersion;
use heterarchy_alexandria_core::document_analysis::{
    DOCUMENT_ANALYSIS_VERSION, DocumentAnalysis, DocumentBatch, DocumentId, DocumentInput,
    DocumentOutcome, FrontmatterEntry, FrontmatterValue, RelativeVaultPath, analyze_batch,
};
use heterarchy_alexandria_core::hash_fingerprint::{HASH_FINGERPRINT_VERSION, sha256_text};
use heterarchy_alexandria_core::markdown_chunking::{
    ChunkBatch, ChunkDocumentInput, ChunkDocumentOutcome, ChunkPolicy, MARKDOWN_CHUNKING_VERSION,
    chunk_batch,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DocumentIndexBatchWire {
    contract_version: u16,
    chunking_version: u16,
    hashing_version: u16,
    max_chars: usize,
    overlap_chars: usize,
    #[serde(default = "default_true")]
    include_chunks: bool,
    documents: Vec<DocumentIndexInputWire>,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DocumentIndexInputWire {
    document_id: String,
    relative_path: String,
    text: String,
}

#[derive(Debug, Serialize)]
struct DocumentIndexBatchOutput {
    contract_version: u16,
    analysis_version: u16,
    chunking_version: u16,
    hashing_version: u16,
    results: Vec<DocumentIndexOutcome>,
}

#[derive(Debug, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
enum DocumentIndexOutcome {
    Success {
        document_id: String,
        relative_path: String,
        analysis: DocumentIndexAnalysis,
        body: String,
        title: String,
        content_hash: String,
        chunks: Vec<DocumentIndexChunk>,
    },
    Error {
        document_id: String,
        relative_path: String,
        error: DocumentIndexFailure,
    },
}

#[derive(Debug, Serialize)]
struct DocumentIndexAnalysis {
    analysis_version: u16,
    frontmatter: Vec<FrontmatterEntry>,
}

#[derive(Debug, Serialize)]
struct DocumentIndexChunk {
    chunk_index: usize,
    heading: Option<String>,
    content: String,
    content_hash: String,
}

#[derive(Debug, Serialize)]
struct DocumentIndexFailure {
    code: &'static str,
    message: String,
    recoverable: bool,
}

pub(crate) fn compute_document_index_batch_payload(payload: &[u8]) -> Result<Vec<u8>, String> {
    let wire: DocumentIndexBatchWire = serde_json::from_slice(payload)
        .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INPUT_ERROR: {error}"))?;
    validate_versions(&wire)?;
    let policy = ChunkPolicy::new(wire.max_chars, wire.overlap_chars)
        .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INPUT_ERROR: {error}"))?;
    let include_chunks = wire.include_chunks;
    let results = wire
        .documents
        .into_iter()
        .map(|document| compute_document(document, policy, include_chunks))
        .collect::<Result<Vec<_>, _>>()?;
    let output = DocumentIndexBatchOutput {
        contract_version: ComputeContractVersion::CURRENT.value(),
        analysis_version: DOCUMENT_ANALYSIS_VERSION,
        chunking_version: MARKDOWN_CHUNKING_VERSION,
        hashing_version: HASH_FINGERPRINT_VERSION,
        results,
    };
    serde_json::to_vec(&output)
        .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: {error}"))
}

fn validate_versions(wire: &DocumentIndexBatchWire) -> Result<(), String> {
    if wire.contract_version != ComputeContractVersion::CURRENT.value() {
        return Err(format!(
            "NATIVE_DOCUMENT_INDEX_CONTRACT_ERROR: expected contract version {}, found {}",
            ComputeContractVersion::CURRENT.value(),
            wire.contract_version
        ));
    }
    if wire.chunking_version != MARKDOWN_CHUNKING_VERSION {
        return Err(format!(
            "NATIVE_DOCUMENT_INDEX_CONTRACT_ERROR: expected chunking version {MARKDOWN_CHUNKING_VERSION}, found {}",
            wire.chunking_version
        ));
    }
    if wire.hashing_version != HASH_FINGERPRINT_VERSION {
        return Err(format!(
            "NATIVE_DOCUMENT_INDEX_CONTRACT_ERROR: expected hashing version {HASH_FINGERPRINT_VERSION}, found {}",
            wire.hashing_version
        ));
    }
    Ok(())
}

fn compute_document(
    input: DocumentIndexInputWire,
    policy: ChunkPolicy,
    include_chunks: bool,
) -> Result<DocumentIndexOutcome, String> {
    let document_id = DocumentId::new(input.document_id.clone())
        .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INPUT_ERROR: {error}"))?;
    let relative_path = RelativeVaultPath::new(input.relative_path.clone())
        .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INPUT_ERROR: {error}"))?;
    let content_hash = sha256_text(&input.text);
    let analysis_input = DocumentInput::new(document_id.clone(), relative_path.clone(), input.text)
        .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INPUT_ERROR: {error}"))?;
    let analysis_result = analyze_batch(
        DocumentBatch::new(vec![analysis_input])
            .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INPUT_ERROR: {error}"))?,
    );
    let outcome = analysis_result.results.into_iter().next().ok_or_else(|| {
        "NATIVE_DOCUMENT_INDEX_INVARIANT_ERROR: missing analysis result".to_owned()
    })?;
    let analysis = match outcome {
        DocumentOutcome::Success { analysis, .. } => analysis,
        DocumentOutcome::Error { error, .. } => {
            return Ok(DocumentIndexOutcome::Error {
                document_id: input.document_id,
                relative_path: input.relative_path,
                error: DocumentIndexFailure {
                    code: "FRONTMATTER_PARSE_ERROR",
                    message: error.message,
                    recoverable: error.recoverable,
                },
            });
        }
    };
    let DocumentAnalysis {
        analysis_version,
        frontmatter,
        mut body,
        ..
    } = analysis;
    while body.ends_with('\n') {
        body.pop();
    }
    let title = title_from_parts(&frontmatter, &body, &input.relative_path);
    let chunks = if include_chunks {
        indexed_chunks(document_id, relative_path, &title, &body, policy)?
    } else {
        Vec::new()
    };
    Ok(DocumentIndexOutcome::Success {
        document_id: input.document_id,
        relative_path: input.relative_path,
        body,
        title,
        content_hash,
        chunks,
        analysis: DocumentIndexAnalysis {
            analysis_version,
            frontmatter,
        },
    })
}

fn indexed_chunks(
    document_id: DocumentId,
    relative_path: RelativeVaultPath,
    title: &str,
    body: &str,
    policy: ChunkPolicy,
) -> Result<Vec<DocumentIndexChunk>, String> {
    if body.trim().is_empty() {
        return Ok(vec![DocumentIndexChunk {
            chunk_index: 0,
            heading: None,
            content: String::new(),
            content_hash: sha256_text(""),
        }]);
    }
    let input = ChunkDocumentInput::new(
        document_id,
        relative_path,
        title.to_owned(),
        body.to_owned(),
    )
    .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INPUT_ERROR: {error}"))?;
    let batch = ChunkBatch::new(policy, vec![input])
        .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INPUT_ERROR: {error}"))?;
    let result = chunk_batch(batch)
        .map_err(|error| format!("NATIVE_DOCUMENT_INDEX_INVARIANT_ERROR: {error}"))?;
    match result
        .results
        .into_iter()
        .next()
        .ok_or_else(|| "NATIVE_DOCUMENT_INDEX_INVARIANT_ERROR: missing chunk result".to_owned())?
    {
        ChunkDocumentOutcome::Success { chunks, .. } => Ok(chunks
            .into_iter()
            .map(|chunk| DocumentIndexChunk {
                chunk_index: chunk.chunk_index,
                heading: chunk.heading,
                content_hash: sha256_text(&chunk.content),
                content: chunk.content,
            })
            .collect()),
        ChunkDocumentOutcome::Error { error, .. } => Err(format!(
            "NATIVE_DOCUMENT_INDEX_CHUNK_ERROR: {}",
            error.message
        )),
    }
}

fn title_from_parts(frontmatter: &[FrontmatterEntry], body: &str, relative_path: &str) -> String {
    if let Some(title) = frontmatter.iter().find_map(|entry| {
        if entry.key != "title" {
            return None;
        }
        match &entry.value {
            FrontmatterValue::String(value) if !value.is_empty() => Some(value.clone()),
            _ => None,
        }
    }) {
        return title;
    }
    if let Some(title) = body.lines().find_map(|line| {
        line.strip_prefix("# ")
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
    }) {
        return title;
    }
    Path::new(relative_path)
        .file_stem()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .unwrap_or(relative_path)
        .to_owned()
}

#[cfg(test)]
mod tests {
    use serde_json::{Value, json};

    use super::compute_document_index_batch_payload;

    fn document_payload(
        document_id: &str,
        relative_path: &str,
        text: &str,
        include_chunks: Option<bool>,
    ) -> Result<Vec<u8>, String> {
        let mut payload = json!({
            "contract_version": 1,
            "chunking_version": 1,
            "hashing_version": 1,
            "max_chars": 1400,
            "overlap_chars": 160,
            "documents": [{
                "document_id": document_id,
                "relative_path": relative_path,
                "text": text,
            }]
        });
        if let Some(include_chunks) = include_chunks {
            payload["include_chunks"] = json!(include_chunks);
        }
        serde_json::to_vec(&payload).map_err(|error| format!("encode payload: {error}"))
    }

    fn document_output(
        document_id: &str,
        relative_path: &str,
        text: &str,
        include_chunks: Option<bool>,
    ) -> Result<Value, String> {
        let payload = document_payload(document_id, relative_path, text, include_chunks)?;
        let encoded = compute_document_index_batch_payload(&payload)?;
        serde_json::from_slice(&encoded).map_err(|error| format!("decode result: {error}"))
    }

    #[test]
    fn computes_analysis_title_chunks_and_hashes_in_one_payload() -> Result<(), String> {
        let payload = br#"{
            "contract_version":1,
            "chunking_version":1,
            "hashing_version":1,
            "max_chars":1400,
            "overlap_chars":160,
            "documents":[{
                "document_id":"note-1",
                "relative_path":"Projects/Example.md",
                "text":"---\ntitle: Canonical Title\n---\n# Body Heading\nHello world\n"
            }]
        }"#;
        let encoded = compute_document_index_batch_payload(payload)?;
        let value: serde_json::Value =
            serde_json::from_slice(&encoded).map_err(|error| format!("decode result: {error}"))?;
        let result = &value["results"][0];
        assert_eq!(result["status"], "success");
        assert_eq!(result["title"], "Canonical Title");
        assert!(result["analysis"].get("body").is_none());
        assert_eq!(result["analysis"]["analysis_version"], 1);
        assert_eq!(result["analysis"]["frontmatter"][0]["key"], "title");
        assert_eq!(result["body"], "# Body Heading\nHello world");
        assert_eq!(result["chunks"][0]["heading"], "Body Heading");
        assert_eq!(result["content_hash"].as_str().map(str::len), Some(64));
        assert_eq!(
            result["chunks"][0]["content_hash"].as_str().map(str::len),
            Some(64)
        );
        Ok(())
    }

    #[test]
    fn preserves_empty_body_index_chunk_contract() -> Result<(), String> {
        let payload = br#"{
            "contract_version":1,
            "chunking_version":1,
            "hashing_version":1,
            "max_chars":1400,
            "overlap_chars":160,
            "documents":[{
                "document_id":"note-1",
                "relative_path":"Projects/Empty.md",
                "text":"---\ntitle: Empty Note\n---\n"
            }]
        }"#;
        let encoded = compute_document_index_batch_payload(payload)?;
        let value: serde_json::Value =
            serde_json::from_slice(&encoded).map_err(|error| format!("decode result: {error}"))?;
        let chunks = value["results"][0]["chunks"]
            .as_array()
            .ok_or_else(|| "missing chunks".to_owned())?;
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0]["content"], "");
        assert!(chunks[0]["heading"].is_null());
        Ok(())
    }

    #[test]
    fn document_index_chunk_modes_preserve_full_result_parity() -> Result<(), String> {
        let corpus = [
            (
                "normal",
                "Projects/Example.md",
                "---\ntitle: Canonical Title\n---\n# Body Heading\nHello world\n",
            ),
            (
                "unicode",
                "Notes/기억.md",
                "---\ntitle: 기억\n---\n# 제목\n안녕하세요 🌌\n",
            ),
            (
                "empty",
                "Projects/Empty.md",
                "---\ntitle: Empty Note\n---\n",
            ),
            (
                "heading title fallback",
                "Projects/Fallback.md",
                "# Body Heading\nHello\n",
            ),
            (
                "path title fallback",
                "Projects/Stem.md",
                "Body without a heading\n",
            ),
        ];

        for (case_id, relative_path, text) in corpus {
            let omitted = document_output(case_id, relative_path, text, None)?;
            let full = document_output(case_id, relative_path, text, Some(true))?;
            assert_eq!(
                omitted, full,
                "include_chunks default mismatch for {case_id}"
            );
            let mut expected_snapshot = full.clone();
            expected_snapshot["results"][0]["chunks"] = json!([]);
            let snapshot = document_output(case_id, relative_path, text, Some(false))?;
            assert_eq!(
                snapshot, expected_snapshot,
                "snapshot mismatch for {case_id}"
            );
        }
        Ok(())
    }

    #[test]
    fn chunk_mode_preserves_frontmatter_parse_errors() -> Result<(), String> {
        let text = "---\ntitle: Broken\n";
        let omitted = document_output("broken", "Projects/Broken.md", text, None)?;
        let explicit = document_output("broken", "Projects/Broken.md", text, Some(true))?;
        let snapshot = document_output("broken", "Projects/Broken.md", text, Some(false))?;

        assert_eq!(omitted, explicit);
        assert_eq!(snapshot, explicit);
        assert_eq!(snapshot["results"][0]["status"], "error");
        assert_eq!(
            snapshot["results"][0]["error"]["code"],
            "FRONTMATTER_PARSE_ERROR"
        );
        assert_eq!(snapshot["results"][0]["error"]["recoverable"], true);
        Ok(())
    }
}
