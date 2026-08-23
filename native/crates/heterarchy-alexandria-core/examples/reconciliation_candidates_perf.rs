//! Deterministic direct-core scaling evidence for reconciliation candidate discovery.

use std::error::Error;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Instant;

use heterarchy_alexandria_core::reconciliation_candidates::{
    CandidatePolicy, ReconciliationItem, TemporalInterval, discover_candidates,
};
use serde::Serialize;

const BLOCK_SIZE: usize = 8;
const VECTOR_DIMENSIONS: usize = 8;
const SCALES: [usize; 3] = [1_000, 10_000, 100_000];

#[derive(Debug, Serialize)]
struct ReconciliationCorePerformanceReport {
    schema_version: u16,
    benchmark: &'static str,
    profile: &'static str,
    block_size: usize,
    vector_dimensions: usize,
    scenarios: Vec<Scenario>,
}

#[derive(Debug, Serialize)]
struct Scenario {
    item_count: usize,
    iterations: usize,
    elapsed_milliseconds: f64,
    items_per_second: f64,
    comparison_pairs: usize,
    comparisons_per_second: f64,
    theoretical_all_pairs: u64,
    comparison_reduction_ratio: f64,
    retained_pairs: usize,
}

fn main() -> Result<(), Box<dyn Error>> {
    let scenarios = SCALES
        .into_iter()
        .map(measure_scenario)
        .collect::<Result<Vec<_>, _>>()?;
    let report = ReconciliationCorePerformanceReport {
        schema_version: 1,
        benchmark: "reconciliation_candidates_direct_core",
        profile: "release",
        block_size: BLOCK_SIZE,
        vector_dimensions: VECTOR_DIMENSIONS,
        scenarios,
    };
    let encoded = serde_json::to_string_pretty(&report)?;
    if let Some(path) = report_path() {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&path, format!("{encoded}\n"))?;
        println!(
            "reconciliation-candidate-core-perf: wrote {}",
            path.display()
        );
    } else {
        println!("{encoded}");
    }
    Ok(())
}

fn measure_scenario(item_count: usize) -> Result<Scenario, Box<dyn Error>> {
    let items = synthetic_items(item_count)?;
    let policy = CandidatePolicy::new(0.99, 0.99, BLOCK_SIZE, 4)?;
    let iterations = iteration_count(item_count);
    let started = Instant::now();
    let mut latest_comparisons = 0;
    let mut latest_retained = 0;
    for _ in 0..iterations {
        let result = discover_candidates(&items, policy)?;
        latest_comparisons = result.metrics.comparison_pairs;
        latest_retained = result.metrics.retained_pairs;
        black_box(result.metrics.qualifying_pairs);
    }
    let seconds = started.elapsed().as_secs_f64();
    let measured_items = measured_count(item_count, iterations)?;
    let measured_comparisons = measured_count(latest_comparisons, iterations)?;
    let theoretical_all_pairs = theoretical_all_pairs(item_count)?;
    let comparison_reduction_ratio = if theoretical_all_pairs == 0 {
        0.0
    } else {
        f64::from(u32::try_from(latest_comparisons)?) / u64_to_f64(theoretical_all_pairs)?
    };
    Ok(Scenario {
        item_count,
        iterations,
        elapsed_milliseconds: seconds * 1_000.0,
        items_per_second: measured_items / seconds,
        comparison_pairs: latest_comparisons,
        comparisons_per_second: measured_comparisons / seconds,
        theoretical_all_pairs,
        comparison_reduction_ratio,
        retained_pairs: latest_retained,
    })
}

fn synthetic_items(item_count: usize) -> Result<Vec<ReconciliationItem>, Box<dyn Error>> {
    let interval = TemporalInterval::new(Some(0), Some(1_000_000))?;
    (0..item_count)
        .map(|index| {
            let mut embedding = vec![0.0; VECTOR_DIMENSIONS];
            let coordinate = index % VECTOR_DIMENSIONS;
            if let Some(value) = embedding.get_mut(coordinate) {
                *value = 1.0;
            }
            ReconciliationItem::new(
                format!("item-{index:06}"),
                None,
                Some(embedding),
                interval,
                vec![format!("block-{}", index / BLOCK_SIZE)],
                Vec::new(),
                Vec::new(),
            )
            .map_err(Into::into)
        })
        .collect()
}

const fn iteration_count(item_count: usize) -> usize {
    match item_count {
        0..=1_000 => 20,
        1_001..=10_000 => 5,
        _ => 1,
    }
}

fn measured_count(item_count: usize, iterations: usize) -> Result<f64, Box<dyn Error>> {
    let value = item_count
        .checked_mul(iterations)
        .ok_or("reconciliation measured-count overflow")?;
    Ok(f64::from(u32::try_from(value)?))
}

fn theoretical_all_pairs(item_count: usize) -> Result<u64, Box<dyn Error>> {
    let count = u64::try_from(item_count)?;
    Ok(count.saturating_mul(count.saturating_sub(1)) / 2)
}

fn u64_to_f64(value: u64) -> Result<f64, Box<dyn Error>> {
    let high = u32::try_from(value >> 32)?;
    let low = u32::try_from(value & u64::from(u32::MAX))?;
    Ok(f64::from(high) * 4_294_967_296.0 + f64::from(low))
}

fn report_path() -> Option<PathBuf> {
    std::env::var_os("HETERARCHY_ALEXANDRIA_RECONCILIATION_CORE_PERF_REPORT").map(PathBuf::from)
}
