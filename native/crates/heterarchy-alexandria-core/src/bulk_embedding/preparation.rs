use super::{
    BULK_EMBEDDING_VERSION, BulkEmbeddingError, BulkEmbeddingPreparation,
    BulkEmbeddingPreparationMetrics, BulkEmbeddingRequest, EmbeddingDocumentInput,
    EmbeddingInputKind, PreparedEmbeddingBatch, PreparedEmbeddingItem, current_contract_version,
};
use crate::text_compat::{collapse_python_whitespace, trim_python_whitespace};

const E5_PASSAGE_PREFIX: &str = "passage: ";

/// Build deterministic document text and bounded model-input batches.
///
/// # Errors
///
/// Returns an error only when metrics arithmetic exceeds platform bounds.
pub fn prepare_embedding_batch(
    request: BulkEmbeddingRequest,
) -> Result<BulkEmbeddingPreparation, BulkEmbeddingError> {
    let BulkEmbeddingRequest {
        model,
        policy,
        documents,
    } = request;
    let source_bytes = documents.iter().try_fold(0_usize, |total, document| {
        total.checked_add(document.byte_count()).ok_or_else(|| {
            BulkEmbeddingError::invalid_input("embedding preparation source byte overflow")
        })
    })?;
    let mut document_text_bytes = 0_usize;
    let mut model_input_bytes = 0_usize;
    let mut batches = Vec::new();
    let mut current_items = Vec::with_capacity(policy.batch_size.min(documents.len()));

    for (input_index, document) in documents.iter().enumerate() {
        let item = prepare_item(input_index, document, model.input_kind);
        document_text_bytes = document_text_bytes
            .checked_add(item.document_text.len())
            .ok_or_else(|| {
                BulkEmbeddingError::invalid_input("embedding document text byte overflow")
            })?;
        model_input_bytes = model_input_bytes
            .checked_add(item.model_input.len())
            .ok_or_else(|| {
                BulkEmbeddingError::invalid_input("embedding model input byte overflow")
            })?;
        current_items.push(item);
        if current_items.len() == policy.batch_size {
            push_batch(&mut batches, &mut current_items);
        }
    }
    if !current_items.is_empty() {
        push_batch(&mut batches, &mut current_items);
    }

    let metrics = BulkEmbeddingPreparationMetrics {
        item_count: batches.iter().map(|batch| batch.items.len()).sum(),
        batch_count: batches.len(),
        source_bytes,
        document_text_bytes,
        model_input_bytes,
    };
    Ok(BulkEmbeddingPreparation {
        contract_version: current_contract_version(),
        embedding_version: BULK_EMBEDDING_VERSION,
        model,
        batches,
        metrics,
    })
}

fn prepare_item(
    input_index: usize,
    document: &EmbeddingDocumentInput,
    input_kind: EmbeddingInputKind,
) -> PreparedEmbeddingItem {
    let document_text = build_document_text(
        &document.content,
        document.title.as_deref(),
        document.heading.as_deref(),
    );
    let model_input = match input_kind {
        EmbeddingInputKind::Plain => document_text.clone(),
        EmbeddingInputKind::E5Passage => {
            format!(
                "{E5_PASSAGE_PREFIX}{}",
                trim_python_whitespace(&document_text)
            )
        }
    };
    PreparedEmbeddingItem {
        input_index,
        item_id: document.item_id.as_str().to_owned(),
        document_text,
        model_input,
    }
}

fn build_document_text(content: &str, title: Option<&str>, heading: Option<&str>) -> String {
    let normalized_title = normalize_optional_text(title);
    let normalized_heading = normalize_optional_text(heading);
    let mut metadata_lines = Vec::with_capacity(2);
    if let Some(title) = &normalized_title {
        metadata_lines.push(format!("Title: {title}"));
    }
    if let Some(heading) = &normalized_heading
        && normalized_title.as_ref() != Some(heading)
    {
        metadata_lines.push(format!("Heading: {heading}"));
    }
    let normalized_content = trim_python_whitespace(content);
    if metadata_lines.is_empty() {
        return normalized_content.to_owned();
    }
    metadata_lines.push(String::new());
    metadata_lines.push(normalized_content.to_owned());
    metadata_lines.join("\n")
}

fn normalize_optional_text(value: Option<&str>) -> Option<String> {
    let normalized = collapse_python_whitespace(value?);
    if normalized.is_empty() {
        None
    } else {
        Some(normalized)
    }
}

fn push_batch(
    batches: &mut Vec<PreparedEmbeddingBatch>,
    current_items: &mut Vec<PreparedEmbeddingItem>,
) {
    let batch_index = batches.len();
    let items = std::mem::take(current_items);
    batches.push(PreparedEmbeddingBatch { batch_index, items });
}
