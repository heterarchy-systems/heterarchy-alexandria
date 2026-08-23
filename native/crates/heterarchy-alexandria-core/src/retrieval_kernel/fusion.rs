use std::collections::{HashMap, HashSet};

use super::{
    BestRetrievalCandidate, CandidateRepresentative, FusedRetrievalCandidate,
    HYBRID_CANDIDATE_MULTIPLIER, MAX_HYBRID_CANDIDATE_LIMIT, RECIPROCAL_RANK_FUSION_CONSTANT,
    RetrievalCandidate, RetrievalKernelError, RetrievalLane, RetrievalScoreInput,
    VECTOR_RECIPROCAL_RANK_WEIGHT, validate_lane_count,
};

const FUSED_RETRIEVAL_REASON: &str = "Context ranked across lexical and semantic vector evidence using best-lane reciprocal-rank fusion.";

/// Compact fusion result that lets Python retain heavyweight candidate objects.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FusedRetrievalIndex {
    /// Representative lane and lane-local index.
    pub representative: CandidateRepresentative,
    /// First unique FTS lane index for this context, when present.
    pub fts_index: Option<usize>,
    /// First unique vector lane index for this context, when present.
    pub vector_index: Option<usize>,
    /// Best-lane reciprocal-rank score.
    pub score: f64,
}

/// Compact best-per-context result retaining only source index and score.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BestRetrievalIndex {
    /// Selected input index.
    pub candidate_index: usize,
    /// Selected input score.
    pub score: f64,
}

trait IdentityInput {
    fn context_id(&self) -> &str;
}

impl IdentityInput for RetrievalCandidate {
    fn context_id(&self) -> &str {
        &self.context_id
    }
}

impl<Identity> IdentityInput for Identity
where
    Identity: AsRef<str>,
{
    fn context_id(&self) -> &str {
        self.as_ref()
    }
}

trait ScoredInput: IdentityInput {
    fn score(&self) -> f64;
}

impl ScoredInput for RetrievalCandidate {
    fn score(&self) -> f64 {
        self.score
    }
}

impl ScoredInput for RetrievalScoreInput {
    fn score(&self) -> f64 {
        self.score
    }
}

impl IdentityInput for RetrievalScoreInput {
    fn context_id(&self) -> &str {
        &self.context_id
    }
}

/// Return the bounded per-lane over-fetch count used before hybrid fusion.
#[must_use]
pub const fn hybrid_candidate_limit(limit: usize) -> usize {
    let multiplied = limit.saturating_mul(HYBRID_CANDIDATE_MULTIPLIER);
    let over_fetched = if multiplied > limit {
        multiplied
    } else {
        limit
    };
    if over_fetched < MAX_HYBRID_CANDIDATE_LIMIT {
        over_fetched
    } else {
        MAX_HYBRID_CANDIDATE_LIMIT
    }
}

/// Merge only context identities and return source indices for low-copy adapter mapping.
///
/// # Errors
///
/// Returns a typed error when a lane is oversized or contains an invalid context identity.
pub fn merge_hybrid_indices<FtsIdentity, VectorIdentity>(
    fts_context_ids: &[FtsIdentity],
    vector_context_ids: &[VectorIdentity],
    limit: usize,
) -> Result<Vec<FusedRetrievalIndex>, RetrievalKernelError>
where
    FtsIdentity: AsRef<str>,
    VectorIdentity: AsRef<str>,
{
    for context_id in fts_context_ids.iter().map(AsRef::as_ref) {
        super::validate_context_id(context_id)?;
    }
    for context_id in vector_context_ids.iter().map(AsRef::as_ref) {
        super::validate_context_id(context_id)?;
    }
    merge_hybrid_indexed(fts_context_ids, vector_context_ids, limit)
}

/// Rank compact context/score inputs and return source indices for low-copy adapter mapping.
///
/// # Errors
///
/// Returns a typed error when the sequence is oversized or contains invalid input.
pub fn rank_best_indices(
    candidates: &[RetrievalScoreInput],
    limit: usize,
) -> Result<Vec<BestRetrievalIndex>, RetrievalKernelError> {
    rank_best_indexed(candidates, limit)
}

/// Rank parallel identity/score slices without taking ownership of identity strings.
///
/// # Errors
///
/// Returns a typed error for mismatched lengths, invalid identities, non-finite scores, or
/// oversized candidate input.
pub fn rank_best_index_values<Identity>(
    context_ids: &[Identity],
    scores: &[f64],
    limit: usize,
) -> Result<Vec<BestRetrievalIndex>, RetrievalKernelError>
where
    Identity: AsRef<str>,
{
    if context_ids.len() != scores.len() {
        return Err(RetrievalKernelError::invalid_input(
            "context_ids and scores must have equal lengths",
        ));
    }
    let inputs = context_ids
        .iter()
        .zip(scores)
        .map(|(identity, &score)| {
            super::validate_context_id(identity.as_ref())?;
            super::validate_finite("score", score)?;
            Ok(ScoreReference { identity, score })
        })
        .collect::<Result<Vec<_>, RetrievalKernelError>>()?;
    rank_best_indexed(&inputs, limit)
}

struct ScoreReference<'a, Identity> {
    identity: &'a Identity,
    score: f64,
}

impl<Identity> IdentityInput for ScoreReference<'_, Identity>
where
    Identity: AsRef<str>,
{
    fn context_id(&self) -> &str {
        self.identity.as_ref()
    }
}

impl<Identity> ScoredInput for ScoreReference<'_, Identity>
where
    Identity: AsRef<str>,
{
    fn score(&self) -> f64 {
        self.score
    }
}

/// Merge caller-ordered FTS/vector candidates with best-lane reciprocal-rank fusion.
///
/// Duplicate contexts inside one lane are ignored after their original lane position has
/// already consumed a rank. FTS is processed before vector candidates. Cross-lane evidence
/// uses the maximum contribution rather than a sum, and equal contributions keep the first
/// representative.
///
/// # Errors
///
/// Returns a typed error when either lane exceeds the bounded candidate cardinality.
pub fn merge_hybrid_candidates(
    fts_candidates: &[RetrievalCandidate],
    vector_candidates: &[RetrievalCandidate],
    limit: usize,
) -> Result<Vec<FusedRetrievalCandidate>, RetrievalKernelError> {
    let compact = merge_hybrid_indexed(fts_candidates, vector_candidates, limit)?;
    compact
        .into_iter()
        .map(|item| materialize_fused(item, fts_candidates, vector_candidates))
        .collect()
}

/// Keep only the strictly highest-scoring candidate per context, then rank descending.
///
/// Equal scores retain the first candidate. Equal context-level scores retain context
/// insertion order, matching Python's stable sort over insertion-ordered dictionaries.
///
/// # Errors
///
/// Returns a typed error when the candidate sequence exceeds the bounded cardinality.
pub fn rank_best_candidates(
    candidates: &[RetrievalCandidate],
    limit: usize,
) -> Result<Vec<BestRetrievalCandidate>, RetrievalKernelError> {
    Ok(rank_best_indexed(candidates, limit)?
        .into_iter()
        .map(|item| BestRetrievalCandidate {
            context_id: candidates[item.candidate_index].context_id.clone(),
            candidate_index: item.candidate_index,
            score: item.score,
        })
        .collect())
}

fn merge_hybrid_indexed<'a, Fts, Vector>(
    fts_candidates: &'a [Fts],
    vector_candidates: &'a [Vector],
    limit: usize,
) -> Result<Vec<FusedRetrievalIndex>, RetrievalKernelError>
where
    Fts: IdentityInput,
    Vector: IdentityInput,
{
    validate_lane_count(RetrievalLane::Fts, fts_candidates.len())?;
    validate_lane_count(RetrievalLane::Vector, vector_candidates.len())?;
    if limit == 0 {
        return Ok(Vec::new());
    }

    let mut evidence_by_context = HashMap::<&str, FusionIndexEvidence>::new();
    let mut next_first_seen = 0_usize;
    merge_lane_indices(
        &mut evidence_by_context,
        &mut next_first_seen,
        RetrievalLane::Fts,
        fts_candidates,
    );
    merge_lane_indices(
        &mut evidence_by_context,
        &mut next_first_seen,
        RetrievalLane::Vector,
        vector_candidates,
    );

    let mut ranked = evidence_by_context.into_values().collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        right
            .fused_score
            .total_cmp(&left.fused_score)
            .then_with(|| left.first_seen.cmp(&right.first_seen))
    });
    ranked.truncate(limit);
    Ok(ranked
        .into_iter()
        .map(FusionIndexEvidence::into_result)
        .collect())
}

fn rank_best_indexed<Candidate>(
    candidates: &[Candidate],
    limit: usize,
) -> Result<Vec<BestRetrievalIndex>, RetrievalKernelError>
where
    Candidate: ScoredInput,
{
    validate_lane_count(RetrievalLane::Fts, candidates.len())?;
    if limit == 0 {
        return Ok(Vec::new());
    }
    let mut best_by_context = HashMap::<&str, BestIndexEvidence>::new();
    let mut next_first_seen = 0_usize;
    for (candidate_index, candidate) in candidates.iter().enumerate() {
        let evidence = best_by_context
            .entry(candidate.context_id())
            .or_insert_with(|| {
                let first_seen = next_first_seen;
                next_first_seen += 1;
                BestIndexEvidence {
                    candidate_index,
                    score: candidate.score(),
                    first_seen,
                }
            });
        if candidate.score() > evidence.score {
            evidence.candidate_index = candidate_index;
            evidence.score = candidate.score();
        }
    }
    let mut ranked = best_by_context.into_values().collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| left.first_seen.cmp(&right.first_seen))
    });
    ranked.truncate(limit);
    Ok(ranked
        .into_iter()
        .map(BestIndexEvidence::into_result)
        .collect())
}

fn merge_lane_indices<'a, Candidate>(
    evidence_by_context: &mut HashMap<&'a str, FusionIndexEvidence>,
    next_first_seen: &mut usize,
    lane: RetrievalLane,
    candidates: &'a [Candidate],
) where
    Candidate: IdentityInput,
{
    let mut seen_context_ids = HashSet::<&str>::new();
    for (lane_index, candidate) in candidates.iter().enumerate() {
        if !seen_context_ids.insert(candidate.context_id()) {
            continue;
        }
        let rank = lane_index + 1;
        let contribution = reciprocal_rank_contribution(lane, rank);
        let evidence = evidence_by_context
            .entry(candidate.context_id())
            .or_insert_with(|| {
                let first_seen = *next_first_seen;
                *next_first_seen += 1;
                FusionIndexEvidence {
                    representative: CandidateRepresentative { lane, lane_index },
                    representative_contribution: contribution,
                    fused_score: 0.0,
                    first_seen,
                    fts_index: None,
                    vector_index: None,
                }
            });
        evidence.fused_score = evidence.fused_score.max(contribution);
        if contribution > evidence.representative_contribution {
            evidence.representative = CandidateRepresentative { lane, lane_index };
            evidence.representative_contribution = contribution;
        }
        match lane {
            RetrievalLane::Fts => evidence.fts_index = Some(lane_index),
            RetrievalLane::Vector => evidence.vector_index = Some(lane_index),
        }
    }
}

fn materialize_fused(
    item: FusedRetrievalIndex,
    fts_candidates: &[RetrievalCandidate],
    vector_candidates: &[RetrievalCandidate],
) -> Result<FusedRetrievalCandidate, RetrievalKernelError> {
    let representative = match item.representative.lane {
        RetrievalLane::Fts => fts_candidates.get(item.representative.lane_index),
        RetrievalLane::Vector => vector_candidates.get(item.representative.lane_index),
    }
    .ok_or_else(|| RetrievalKernelError::invalid_input("fusion representative index is invalid"))?;
    let fts_score = item
        .fts_index
        .and_then(|index| fts_candidates.get(index))
        .and_then(|candidate| candidate.fts_score);
    let vector_score = item
        .vector_index
        .and_then(|index| vector_candidates.get(index))
        .and_then(|candidate| candidate.vector_score);
    let why_retrieved = if fts_score.is_some() && vector_score.is_some() {
        FUSED_RETRIEVAL_REASON.to_owned()
    } else {
        representative.why_retrieved.clone()
    };
    Ok(FusedRetrievalCandidate {
        context_id: representative.context_id.clone(),
        representative: item.representative,
        score: item.score,
        fts_score,
        vector_score,
        why_retrieved,
    })
}

fn reciprocal_rank_contribution(lane: RetrievalLane, rank: usize) -> f64 {
    let rank = u32::try_from(rank).map_or(f64::from(u32::MAX), f64::from);
    let denominator = f64::from(RECIPROCAL_RANK_FUSION_CONSTANT) + rank;
    let contribution = 1.0 / denominator;
    match lane {
        RetrievalLane::Fts => contribution,
        RetrievalLane::Vector => contribution * VECTOR_RECIPROCAL_RANK_WEIGHT,
    }
}

struct FusionIndexEvidence {
    representative: CandidateRepresentative,
    representative_contribution: f64,
    fused_score: f64,
    first_seen: usize,
    fts_index: Option<usize>,
    vector_index: Option<usize>,
}

impl FusionIndexEvidence {
    fn into_result(self) -> FusedRetrievalIndex {
        FusedRetrievalIndex {
            representative: self.representative,
            fts_index: self.fts_index,
            vector_index: self.vector_index,
            score: self.fused_score,
        }
    }
}

struct BestIndexEvidence {
    candidate_index: usize,
    score: f64,
    first_seen: usize,
}

impl BestIndexEvidence {
    fn into_result(self) -> BestRetrievalIndex {
        BestRetrievalIndex {
            candidate_index: self.candidate_index,
            score: self.score,
        }
    }
}
