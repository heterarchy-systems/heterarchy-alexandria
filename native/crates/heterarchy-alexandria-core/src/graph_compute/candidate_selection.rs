//! Deterministic bounded selection over graph traversal candidates.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};

use super::{
    GraphCandidatePathHop, GraphCandidateSelection, GraphComputeError, GraphProjection,
    GraphProjectionEdge, GraphSelectedCandidate, GraphTitleRelevance, GraphTraversalRequest,
    GraphTraversalResult, TraversalDirection,
};

#[derive(Debug, Clone, Copy)]
struct CandidateAccumulator {
    min_depth: usize,
    seed_support: usize,
    first_seen: usize,
}

#[derive(Debug, Clone)]
struct RankedCandidate {
    note_id: String,
    min_depth: usize,
    seed_support: usize,
    first_seen: usize,
    shared_title_trigrams: usize,
    title_trigram_union: usize,
}

pub(super) fn select_candidates(
    projection: &GraphProjection,
    traversals: Vec<GraphTraversalResult>,
    traversal_requests: &[GraphTraversalRequest],
    primary_note_ids: &[String],
    query: &str,
    max_candidates: usize,
    min_shared_trigrams: usize,
) -> Result<GraphCandidateSelection, GraphComputeError> {
    let query_trigrams = normalized_trigrams(query);
    if query_trigrams.is_empty() {
        return Ok(GraphCandidateSelection {
            traversals,
            candidates: Vec::new(),
            primary_title_relevance: Vec::new(),
        });
    }
    let titles = projection
        .nodes
        .iter()
        .map(|node| (node.note_id.as_str(), node.title.as_str()))
        .collect::<BTreeMap<_, _>>();
    let seeds = traversals
        .iter()
        .map(|result| result.start_note_id.as_str())
        .collect::<BTreeSet<_>>();
    let mut accumulators = BTreeMap::<&str, CandidateAccumulator>::new();
    let mut first_seen = 0_usize;
    for traversal in &traversals {
        for visit in &traversal.visits {
            if seeds.contains(visit.note_id.as_str()) {
                continue;
            }
            if let Some(candidate) = accumulators.get_mut(visit.note_id.as_str()) {
                candidate.min_depth = candidate.min_depth.min(visit.depth);
                candidate.seed_support = candidate.seed_support.saturating_add(1);
            } else {
                accumulators.insert(
                    visit.note_id.as_str(),
                    CandidateAccumulator {
                        min_depth: visit.depth,
                        seed_support: 1,
                        first_seen,
                    },
                );
                first_seen = first_seen.saturating_add(1);
            }
        }
    }
    let mut ranked = accumulators
        .into_iter()
        .filter_map(|(note_id, accumulator)| {
            let title = titles.get(note_id)?;
            let title_trigrams = normalized_trigrams(title);
            let shared_title_trigrams = query_trigrams.intersection(&title_trigrams).count();
            if shared_title_trigrams < min_shared_trigrams {
                return None;
            }
            let title_trigram_union = query_trigrams.union(&title_trigrams).count();
            (title_trigram_union > 0).then(|| RankedCandidate {
                note_id: note_id.to_owned(),
                min_depth: accumulator.min_depth,
                seed_support: accumulator.seed_support,
                first_seen: accumulator.first_seen,
                shared_title_trigrams,
                title_trigram_union,
            })
        })
        .collect::<Vec<_>>();
    ranked.sort_by(compare_ranked_candidates);
    let primary_title_relevance = primary_note_ids
        .iter()
        .filter_map(|note_id| title_relevance(note_id, &titles, &query_trigrams))
        .collect();
    let candidates = ranked
        .into_iter()
        .take(max_candidates)
        .map(|candidate| {
            let path_hops = candidate_path_hops(
                projection,
                &traversals,
                traversal_requests,
                &candidate.note_id,
                candidate.min_depth,
            )?;
            Ok(GraphSelectedCandidate {
                note_id: candidate.note_id,
                min_depth: candidate.min_depth,
                seed_support: candidate.seed_support,
                shared_title_trigrams: candidate.shared_title_trigrams,
                title_trigram_union: candidate.title_trigram_union,
                path_hops,
            })
        })
        .collect::<Result<Vec<_>, GraphComputeError>>()?;
    Ok(GraphCandidateSelection {
        traversals,
        candidates,
        primary_title_relevance,
    })
}

fn candidate_path_hops(
    projection: &GraphProjection,
    traversals: &[GraphTraversalResult],
    traversal_requests: &[GraphTraversalRequest],
    candidate_note_id: &str,
    min_depth: usize,
) -> Result<Vec<GraphCandidatePathHop>, GraphComputeError> {
    for (traversal, request) in traversals.iter().zip(traversal_requests) {
        let reaches_candidate = traversal
            .visits
            .iter()
            .any(|visit| visit.note_id == candidate_note_id && visit.depth == min_depth);
        if reaches_candidate {
            return path_hops_for_traversal(
                projection,
                traversal,
                request,
                candidate_note_id,
                min_depth,
            );
        }
    }
    Err(GraphComputeError::new(format!(
        "selected graph candidate {candidate_note_id} has no traversal at depth {min_depth}"
    )))
}

fn path_hops_for_traversal(
    projection: &GraphProjection,
    traversal: &GraphTraversalResult,
    request: &GraphTraversalRequest,
    candidate_note_id: &str,
    min_depth: usize,
) -> Result<Vec<GraphCandidatePathHop>, GraphComputeError> {
    let mut current_note_id = candidate_note_id.to_owned();
    let mut current_depth = min_depth;
    let mut reversed = Vec::with_capacity(min_depth);
    while current_depth > 0 {
        let predecessor_depth = current_depth.saturating_sub(1);
        let mut selected = None;
        for visit in &traversal.visits {
            if visit.depth != predecessor_depth {
                continue;
            }
            if let Some((edge, direction)) =
                matching_path_edge(projection, request, &visit.note_id, &current_note_id)
            {
                selected = Some((visit.note_id.clone(), edge, direction));
                break;
            }
        }
        let Some((predecessor_note_id, edge, direction)) = selected else {
            return Err(GraphComputeError::new(format!(
                "selected graph candidate {candidate_note_id} has no deterministic predecessor at depth {current_depth}"
            )));
        };
        reversed.push(GraphCandidatePathHop {
            edge_id: edge.edge_id.clone(),
            source_note_id: predecessor_note_id.clone(),
            target_note_id: current_note_id,
            relation: edge.relation.clone(),
            direction,
            depth: current_depth,
        });
        current_note_id = predecessor_note_id;
        current_depth = predecessor_depth;
    }
    if current_note_id != traversal.start_note_id {
        return Err(GraphComputeError::new(format!(
            "selected graph candidate {candidate_note_id} path does not terminate at seed {}",
            traversal.start_note_id
        )));
    }
    reversed.reverse();
    Ok(reversed)
}

fn matching_path_edge<'projection>(
    projection: &'projection GraphProjection,
    request: &GraphTraversalRequest,
    predecessor_note_id: &str,
    target_note_id: &str,
) -> Option<(&'projection GraphProjectionEdge, TraversalDirection)> {
    let relation_allowed = |edge: &GraphProjectionEdge| {
        request.relations.is_empty()
            || request
                .relations
                .iter()
                .any(|relation| relation == &edge.relation)
    };
    let mut matches = projection
        .edges
        .iter()
        .filter(|edge| relation_allowed(edge))
        .filter_map(|edge| {
            let outgoing =
                edge.source_note_id == predecessor_note_id && edge.target_note_id == target_note_id;
            let incoming =
                edge.target_note_id == predecessor_note_id && edge.source_note_id == target_note_id;
            let direction = match request.direction {
                TraversalDirection::Outgoing | TraversalDirection::Both if outgoing => {
                    Some(TraversalDirection::Outgoing)
                }
                TraversalDirection::Incoming | TraversalDirection::Both if incoming => {
                    Some(TraversalDirection::Incoming)
                }
                _ => None,
            }?;
            Some((edge, direction))
        })
        .collect::<Vec<_>>();
    matches.sort_by(
        |(left_edge, left_direction), (right_edge, right_direction)| {
            (left_edge.edge_id.as_str(), direction_order(*left_direction)).cmp(&(
                right_edge.edge_id.as_str(),
                direction_order(*right_direction),
            ))
        },
    );
    matches.into_iter().next()
}

fn direction_order(direction: TraversalDirection) -> u8 {
    match direction {
        TraversalDirection::Outgoing => 0,
        TraversalDirection::Incoming => 1,
        TraversalDirection::Both => 2,
    }
}

fn title_relevance(
    note_id: &str,
    titles: &BTreeMap<&str, &str>,
    query_trigrams: &BTreeSet<[char; 3]>,
) -> Option<GraphTitleRelevance> {
    let title = titles.get(note_id)?;
    let title_trigrams = normalized_trigrams(title);
    let title_trigram_union = query_trigrams.union(&title_trigrams).count();
    (title_trigram_union > 0).then(|| GraphTitleRelevance {
        note_id: note_id.to_owned(),
        shared_title_trigrams: query_trigrams.intersection(&title_trigrams).count(),
        title_trigram_union,
    })
}

fn compare_ranked_candidates(left: &RankedCandidate, right: &RankedCandidate) -> Ordering {
    let left_cross = (left.shared_title_trigrams as u128) * (right.title_trigram_union as u128);
    let right_cross = (right.shared_title_trigrams as u128) * (left.title_trigram_union as u128);
    right_cross
        .cmp(&left_cross)
        .then_with(|| left.min_depth.cmp(&right.min_depth))
        .then_with(|| right.seed_support.cmp(&left.seed_support))
        .then_with(|| left.first_seen.cmp(&right.first_seen))
        .then_with(|| left.note_id.cmp(&right.note_id))
}

fn normalized_trigrams(value: &str) -> BTreeSet<[char; 3]> {
    let mut normalized = Vec::with_capacity(value.chars().count());
    let mut separator_pending = false;
    for character in value.chars() {
        if character.is_alphanumeric() {
            if separator_pending && !normalized.is_empty() {
                normalized.push('_');
            }
            normalized.extend(character.to_lowercase());
            separator_pending = false;
        } else if !normalized.is_empty() {
            separator_pending = true;
        }
    }
    normalized
        .windows(3)
        .map(|window| [window[0], window[1], window[2]])
        .collect()
}

#[cfg(test)]
mod tests {
    use super::{compare_ranked_candidates, normalized_trigrams};
    use crate::graph_compute::candidate_selection::RankedCandidate;

    #[test]
    fn normalizes_multilingual_text_into_stable_character_trigrams() {
        let trigrams = normalized_trigrams("Graph-aware 검색 품질");
        assert!(trigrams.contains(&['g', 'r', 'a']));
        assert!(trigrams.contains(&['검', '색', '_']));
        assert!(trigrams.contains(&['_', '품', '질']));
    }

    #[test]
    fn compares_similarity_before_distance_support_and_stable_order() {
        let stronger_similarity = RankedCandidate {
            note_id: "b".to_owned(),
            min_depth: 2,
            seed_support: 1,
            first_seen: 2,
            shared_title_trigrams: 6,
            title_trigram_union: 12,
        };
        let weaker_similarity = RankedCandidate {
            note_id: "a".to_owned(),
            min_depth: 1,
            seed_support: 2,
            first_seen: 1,
            shared_title_trigrams: 4,
            title_trigram_union: 12,
        };
        assert!(compare_ranked_candidates(&stronger_similarity, &weaker_similarity).is_lt());
    }
}
