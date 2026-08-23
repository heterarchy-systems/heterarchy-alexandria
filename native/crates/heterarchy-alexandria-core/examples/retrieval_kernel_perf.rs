//! Deterministic direct-core performance evidence for the retrieval ranking kernel.

use std::error::Error;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Instant;

use heterarchy_alexandria_core::retrieval_kernel::{
    RetrievalCandidate, merge_hybrid_candidates, rank_best_candidates,
};
use serde::Serialize;

const RESULT_LIMIT: usize = 50;
const SCALES: [usize; 4] = [50, 1_000, 10_000, 50_000];

#[derive(Debug, Serialize)]
struct RetrievalCorePerformanceReport {
    schema_version: u16,
    benchmark: &'static str,
    profile: &'static str,
    result_limit: usize,
    scenarios: Vec<RetrievalCorePerformanceScenario>,
}

#[derive(Debug, Serialize)]
struct RetrievalCorePerformanceScenario {
    candidates_per_lane: usize,
    total_candidate_count: usize,
    iterations: usize,
    fusion_total_milliseconds: f64,
    fusion_microseconds_per_candidate: f64,
    fusion_candidates_per_second: f64,
    best_match_total_milliseconds: f64,
    best_match_microseconds_per_candidate: f64,
    best_match_candidates_per_second: f64,
}

fn main() -> Result<(), Box<dyn Error>> {
    let scenarios = SCALES
        .into_iter()
        .map(measure_scenario)
        .collect::<Result<Vec<_>, _>>()?;
    let report = RetrievalCorePerformanceReport {
        schema_version: 1,
        benchmark: "retrieval_kernel_direct_core",
        profile: "release",
        result_limit: RESULT_LIMIT,
        scenarios,
    };
    let encoded = serde_json::to_string_pretty(&report)?;
    if let Some(path) = report_path() {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&path, format!("{encoded}\n"))?;
        println!("retrieval-kernel-core-perf: wrote {}", path.display());
    } else {
        println!("{encoded}");
    }
    Ok(())
}

fn measure_scenario(
    candidates_per_lane: usize,
) -> Result<RetrievalCorePerformanceScenario, Box<dyn Error>> {
    let iterations = iteration_count(candidates_per_lane);
    let fts_candidates = fts_candidates(candidates_per_lane)?;
    let vector_candidates = vector_candidates(candidates_per_lane)?;
    let total_candidate_count = candidates_per_lane
        .checked_mul(2)
        .ok_or("retrieval candidate count overflow")?;

    let fusion_started = Instant::now();
    for _ in 0..iterations {
        let fused = merge_hybrid_candidates(&fts_candidates, &vector_candidates, RESULT_LIMIT)?;
        black_box(fused.len());
    }
    let fusion_seconds = fusion_started.elapsed().as_secs_f64();

    let best_match_started = Instant::now();
    for _ in 0..iterations {
        let ranked = rank_best_candidates(&fts_candidates, RESULT_LIMIT)?;
        black_box(ranked.len());
    }
    let best_match_seconds = best_match_started.elapsed().as_secs_f64();

    let fused_measured_candidates = measured_count(total_candidate_count, iterations)?;
    let best_measured_candidates = measured_count(candidates_per_lane, iterations)?;
    Ok(RetrievalCorePerformanceScenario {
        candidates_per_lane,
        total_candidate_count,
        iterations,
        fusion_total_milliseconds: fusion_seconds * 1_000.0,
        fusion_microseconds_per_candidate: fusion_seconds * 1_000_000.0 / fused_measured_candidates,
        fusion_candidates_per_second: fused_measured_candidates / fusion_seconds,
        best_match_total_milliseconds: best_match_seconds * 1_000.0,
        best_match_microseconds_per_candidate: best_match_seconds * 1_000_000.0
            / best_measured_candidates,
        best_match_candidates_per_second: best_measured_candidates / best_match_seconds,
    })
}

fn fts_candidates(count: usize) -> Result<Vec<RetrievalCandidate>, Box<dyn Error>> {
    (0..count)
        .map(|index| {
            let context_index = duplicate_adjusted_index(index, 17);
            RetrievalCandidate::new(
                format!("context-{context_index}"),
                descending_score(index, count),
                Some(descending_score(index, count)),
                None,
                "lexical candidate".to_owned(),
            )
            .map_err(Into::into)
        })
        .collect()
}

fn vector_candidates(count: usize) -> Result<Vec<RetrievalCandidate>, Box<dyn Error>> {
    (0..count)
        .map(|index| {
            let context_id = if index % 5 == 0 {
                format!("vector-only-{index}")
            } else {
                let context_index = duplicate_adjusted_index(index, 19);
                format!("context-{context_index}")
            };
            RetrievalCandidate::new(
                context_id,
                descending_score(index, count),
                None,
                Some(descending_score(index, count)),
                "semantic vector candidate".to_owned(),
            )
            .map_err(Into::into)
        })
        .collect()
}

const fn duplicate_adjusted_index(index: usize, cadence: usize) -> usize {
    if index > 0 && index.is_multiple_of(cadence) {
        index - 1
    } else {
        index
    }
}

fn descending_score(index: usize, count: usize) -> f64 {
    let numerator = u32::try_from(count.saturating_sub(index)).unwrap_or(u32::MAX);
    let denominator = count.saturating_add(1).next_power_of_two();
    let denominator = u32::try_from(denominator).unwrap_or(u32::MAX);
    f64::from(numerator) / f64::from(denominator)
}

const fn iteration_count(candidates_per_lane: usize) -> usize {
    match candidates_per_lane {
        0..=50 => 1_000,
        51..=1_000 => 100,
        1_001..=10_000 => 10,
        _ => 2,
    }
}

fn measured_count(candidate_count: usize, iterations: usize) -> Result<f64, Box<dyn Error>> {
    let value = candidate_count
        .checked_mul(iterations)
        .ok_or("retrieval measured-candidate count overflow")?;
    Ok(f64::from(u32::try_from(value)?))
}

fn report_path() -> Option<PathBuf> {
    std::env::var_os("HETERARCHY_ALEXANDRIA_RETRIEVAL_CORE_PERF_REPORT").map(PathBuf::from)
}
