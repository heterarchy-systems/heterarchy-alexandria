//! Deterministic direct-core performance evidence for bulk embedding preparation/finalization.

use std::error::Error;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Instant;

use heterarchy_alexandria_core::bulk_embedding::{
    BulkEmbeddingPolicy, BulkEmbeddingRequest, EmbeddingDocumentInput, EmbeddingInputKind,
    EmbeddingModelContract, InferenceBatchOutput, finalize_embedding_batch,
    prepare_embedding_batch,
};
use heterarchy_alexandria_core::document_analysis::DocumentId;
use serde::Serialize;

const DIMENSIONS: usize = 384;
const BATCH_SIZE: usize = 16;
const SCALES: [usize; 5] = [1, 16, 100, 1_000, 10_000];

#[derive(Debug, Serialize)]
struct CorePerformanceReport {
    schema_version: u16,
    benchmark: &'static str,
    profile: &'static str,
    dimensions: usize,
    batch_size: usize,
    scenarios: Vec<CorePerformanceScenario>,
}

#[derive(Debug, Serialize)]
struct CorePerformanceScenario {
    item_count: usize,
    iterations: usize,
    preparation_total_milliseconds: f64,
    preparation_microseconds_per_item: f64,
    preparation_items_per_second: f64,
    finalization_total_milliseconds: f64,
    finalization_microseconds_per_item: f64,
    finalization_items_per_second: f64,
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut scenarios = Vec::with_capacity(SCALES.len());
    for item_count in SCALES {
        scenarios.push(measure_scenario(item_count)?);
    }
    let report = CorePerformanceReport {
        schema_version: 1,
        benchmark: "bulk_embedding_direct_core",
        profile: "release",
        dimensions: DIMENSIONS,
        batch_size: BATCH_SIZE,
        scenarios,
    };
    let encoded = serde_json::to_string_pretty(&report)?;
    if let Some(path) = report_path() {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&path, format!("{encoded}\n"))?;
        println!("bulk-embedding-core-perf: wrote {}", path.display());
    } else {
        println!("{encoded}");
    }
    Ok(())
}

fn measure_scenario(item_count: usize) -> Result<CorePerformanceScenario, Box<dyn Error>> {
    let iterations = iteration_count(item_count);
    let request = request(item_count)?;

    let preparation_started = Instant::now();
    for _ in 0..iterations {
        let prepared = prepare_embedding_batch(request.clone())?;
        black_box(prepared.metrics.model_input_bytes);
    }
    let preparation_seconds = preparation_started.elapsed().as_secs_f64();

    let prepared = prepare_embedding_batch(request)?;
    let inference_template = synthetic_inference(&prepared);
    let finalization_started = Instant::now();
    for _ in 0..iterations {
        let result = finalize_embedding_batch(prepared.clone(), inference_template.clone())?;
        black_box(result.metrics.vector_value_count);
    }
    let finalization_seconds = finalization_started.elapsed().as_secs_f64();

    let measured_items = usize_to_f64(
        item_count
            .checked_mul(iterations)
            .ok_or("bulk embedding performance measured-item count overflow")?,
    )?;
    Ok(CorePerformanceScenario {
        item_count,
        iterations,
        preparation_total_milliseconds: preparation_seconds * 1_000.0,
        preparation_microseconds_per_item: preparation_seconds * 1_000_000.0 / measured_items,
        preparation_items_per_second: measured_items / preparation_seconds,
        finalization_total_milliseconds: finalization_seconds * 1_000.0,
        finalization_microseconds_per_item: finalization_seconds * 1_000_000.0 / measured_items,
        finalization_items_per_second: measured_items / finalization_seconds,
    })
}

fn request(item_count: usize) -> Result<BulkEmbeddingRequest, Box<dyn Error>> {
    let model = EmbeddingModelContract {
        provider: "FASTEMBED_LOCAL".to_owned(),
        model: "intfloat/multilingual-e5-small".to_owned(),
        provider_version: "candidate".to_owned(),
        pooling_mode: "mean".to_owned(),
        normalize: true,
        dimensions: DIMENSIONS,
        document_input_format: "metadata-v1+e5-passage-prefix-v1".to_owned(),
        input_kind: EmbeddingInputKind::E5Passage,
    };
    let policy = BulkEmbeddingPolicy::new(BATCH_SIZE)?;
    let documents = (0..item_count)
        .map(document)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(BulkEmbeddingRequest::new(model, policy, documents)?)
}

fn document(index: usize) -> Result<EmbeddingDocumentInput, Box<dyn Error>> {
    let item_id = DocumentId::new(format!("perf-chunk-{index}"))?;
    let content = format!(
        "검색 품질과 deterministic ranking evidence를 검증하는 representative chunk {index}."
    );
    Ok(EmbeddingDocumentInput::new(
        item_id,
        content,
        Some("Alexandria retrieval performance".to_owned()),
        Some(format!("Bulk embedding scenario {index}")),
    )?)
}

fn synthetic_inference(
    preparation: &heterarchy_alexandria_core::bulk_embedding::BulkEmbeddingPreparation,
) -> Vec<InferenceBatchOutput> {
    preparation
        .batches
        .iter()
        .map(|batch| {
            InferenceBatchOutput::new(
                batch.batch_index,
                vec![vec![0.0; DIMENSIONS]; batch.items.len()],
            )
        })
        .collect()
}

const fn iteration_count(item_count: usize) -> usize {
    match item_count {
        0..=1 => 5_000,
        2..=16 => 1_000,
        17..=100 => 300,
        101..=1_000 => 30,
        _ => 3,
    }
}

fn usize_to_f64(value: usize) -> Result<f64, Box<dyn Error>> {
    let value = u32::try_from(value)?;
    Ok(f64::from(value))
}

fn report_path() -> Option<PathBuf> {
    std::env::var_os("HETERARCHY_ALEXANDRIA_CORE_PERF_REPORT").map(PathBuf::from)
}
