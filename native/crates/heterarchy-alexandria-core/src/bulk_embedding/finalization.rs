use super::{
    BULK_EMBEDDING_VERSION, BulkEmbeddingError, BulkEmbeddingErrorCode, BulkEmbeddingPreparation,
    BulkEmbeddingResult, BulkEmbeddingResultMetrics, EmbeddingRecord, InferenceBatchOutput,
    current_contract_version,
};

/// Validate runtime vectors while preserving exact input identity and order.
///
/// The current Python contract is fail-fast for a provider batch. This function therefore
/// returns one typed error instead of inventing per-item persistence or retry semantics.
///
/// # Errors
///
/// Returns an error for batch/order/cardinality drift, wrong dimensions, non-finite values,
/// or metrics overflow.
pub fn finalize_embedding_batch(
    preparation: BulkEmbeddingPreparation,
    inference_batches: Vec<InferenceBatchOutput>,
) -> Result<BulkEmbeddingResult, BulkEmbeddingError> {
    if inference_batches.len() != preparation.batches.len() {
        return Err(BulkEmbeddingError::batch(
            BulkEmbeddingErrorCode::CardinalityMismatch,
            format!(
                "embedding runtime returned {} batches for {} prepared batches",
                inference_batches.len(),
                preparation.batches.len()
            ),
            first_mismatched_batch_index(preparation.batches.len(), inference_batches.len()),
        ));
    }

    let mut records = Vec::with_capacity(preparation.metrics.item_count);
    for (prepared_batch, inference_batch) in preparation.batches.iter().zip(inference_batches) {
        validate_batch_identity(prepared_batch.batch_index, inference_batch.batch_index)?;
        if inference_batch.vectors.len() != prepared_batch.items.len() {
            return Err(BulkEmbeddingError::batch(
                BulkEmbeddingErrorCode::CardinalityMismatch,
                format!(
                    "embedding batch {} returned {} vectors for {} prepared items",
                    prepared_batch.batch_index,
                    inference_batch.vectors.len(),
                    prepared_batch.items.len()
                ),
                prepared_batch.batch_index,
            ));
        }
        for (item, vector) in prepared_batch.items.iter().zip(inference_batch.vectors) {
            validate_vector(
                prepared_batch.batch_index,
                item,
                &vector,
                preparation.model.dimensions,
            )?;
            records.push(EmbeddingRecord {
                input_index: item.input_index,
                item_id: item.item_id.clone(),
                dimensions: vector.len(),
                vector,
            });
        }
    }
    records.sort_by_key(|record| record.input_index);
    validate_contiguous_order(&records)?;
    let vector_value_count = records
        .len()
        .checked_mul(preparation.model.dimensions)
        .ok_or_else(|| BulkEmbeddingError {
            code: BulkEmbeddingErrorCode::NumericOverflow,
            message: "embedding vector scalar count overflow".to_owned(),
            batch_index: None,
            input_index: None,
            item_id: None,
        })?;
    let metrics = BulkEmbeddingResultMetrics {
        item_count: records.len(),
        batch_count: preparation.batches.len(),
        dimensions: preparation.model.dimensions,
        vector_value_count,
    };
    Ok(BulkEmbeddingResult {
        contract_version: current_contract_version(),
        embedding_version: BULK_EMBEDDING_VERSION,
        model: preparation.model,
        records,
        metrics,
    })
}

fn validate_batch_identity(expected: usize, actual: usize) -> Result<(), BulkEmbeddingError> {
    if actual != expected {
        return Err(BulkEmbeddingError::batch(
            BulkEmbeddingErrorCode::CardinalityMismatch,
            format!("embedding batch order drift: expected batch {expected}, found {actual}"),
            expected,
        ));
    }
    Ok(())
}

fn validate_vector(
    batch_index: usize,
    item: &super::PreparedEmbeddingItem,
    vector: &[f32],
    expected_dimensions: usize,
) -> Result<(), BulkEmbeddingError> {
    if vector.len() != expected_dimensions {
        return Err(BulkEmbeddingError::item(
            BulkEmbeddingErrorCode::DimensionMismatch,
            format!(
                "embedding vector has unexpected dimensions: expected {expected_dimensions}, received {}",
                vector.len()
            ),
            batch_index,
            item,
        ));
    }
    if vector.iter().any(|value| !value.is_finite()) {
        return Err(BulkEmbeddingError::item(
            BulkEmbeddingErrorCode::NonFiniteVector,
            "embedding vector contains a non-finite value",
            batch_index,
            item,
        ));
    }
    Ok(())
}

fn validate_contiguous_order(records: &[EmbeddingRecord]) -> Result<(), BulkEmbeddingError> {
    for (expected, record) in records.iter().enumerate() {
        if record.input_index != expected {
            return Err(BulkEmbeddingError {
                code: BulkEmbeddingErrorCode::CardinalityMismatch,
                message: format!(
                    "embedding output order is not contiguous: expected input {expected}, found {}",
                    record.input_index
                ),
                batch_index: None,
                input_index: Some(record.input_index),
                item_id: Some(record.item_id.clone()),
            });
        }
    }
    Ok(())
}

const fn first_mismatched_batch_index(expected: usize, actual: usize) -> usize {
    if expected < actual { expected } else { actual }
}
