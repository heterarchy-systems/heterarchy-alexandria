//! Deterministic cross-note validation for Context reindex manifests.
//!
//! Python remains authoritative for Markdown parsing, Unicode/path canonicalization,
//! persistence, and operator-facing reindex effects. This module receives already
//! normalized candidate fields and computes only deterministic acceptance and issues.

use std::collections::{HashMap, HashSet, VecDeque};

use serde::Serialize;

/// Version of the deterministic Context reindex-manifest compute contract.
pub const CONTEXT_REINDEX_MANIFEST_VERSION: u16 = 1;

/// Context identity fields participating in duplicate-content detection.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ContextReindexIdentity {
    /// Canonical recall scope text.
    pub scope: Option<String>,
    /// Optional project identity.
    pub project: Option<String>,
    /// Optional workspace identity.
    pub workspace_id: Option<String>,
    /// Optional agent identity.
    pub agent_id: Option<String>,
    /// Optional user identity.
    pub user_id: Option<String>,
    /// Optional session identity.
    pub session_id: Option<String>,
    /// Canonical content hash stored in Context frontmatter.
    pub content_hash: Option<String>,
}

/// One already-normalized managed-note candidate participating in manifest validation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContextReindexManifestCandidate {
    /// Stable managed-note identity.
    pub note_id: String,
    /// Original logical relative path retained for operator-facing issue messages.
    pub relative_path: String,
    /// Python-canonicalized relative path used only for collision detection.
    pub canonical_relative_path: String,
    /// Whether this candidate is a canonical Context note.
    pub is_context: bool,
    /// Context duplicate signature fields; ignored for non-Context candidates.
    pub identity: ContextReindexIdentity,
    /// Forward supersede reference after Python string-only normalization.
    pub supersedes_context_id: Option<String>,
    /// Backlink supersede reference after Python string-only normalization.
    pub superseded_by_context_id: Option<String>,
}

/// One candidate rejected by deterministic manifest validation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ContextReindexManifestIssue {
    /// Original candidate relative path.
    pub relative_path: String,
    /// Stable candidate identity.
    pub context_id: String,
    /// Exact Python-compatible operator-facing validation message.
    pub message: String,
}

/// Deterministic validation result expressed as original candidate indices and issues.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ContextReindexManifestResult {
    /// Original candidate indices accepted for downstream indexing.
    pub accepted_indices: Vec<usize>,
    /// Issues ordered exactly as the current Python validator emits them.
    pub issues: Vec<ContextReindexManifestIssue>,
}

/// Validate normalized candidates while preserving current Python ordering and messages.
#[must_use]
pub fn validate_context_reindex_manifest(
    candidates: &[ContextReindexManifestCandidate],
) -> ContextReindexManifestResult {
    let mut issues = Vec::new();
    let colliding_paths = colliding_canonical_paths(candidates);
    let mut note_paths_by_id: HashMap<&str, &str> = HashMap::new();
    let mut context_paths_by_signature: HashMap<&ContextReindexIdentity, &str> = HashMap::new();
    let mut valid_indices = Vec::with_capacity(candidates.len());

    for (candidate_index, candidate) in candidates.iter().enumerate() {
        if colliding_paths.contains(candidate.canonical_relative_path.as_str()) {
            issues.push(issue(
                candidate,
                format!(
                    "DUPLICATE_CANONICAL_PATH: multiple physical notes normalize to {}",
                    candidate.canonical_relative_path
                ),
            ));
            continue;
        }
        if let Some(existing_path) = note_paths_by_id.get(candidate.note_id.as_str()) {
            issues.push(issue(
                candidate,
                format!(
                    "DUPLICATE_CONTEXT_ID: {} is also declared by {existing_path}",
                    candidate.note_id
                ),
            ));
            continue;
        }
        note_paths_by_id.insert(&candidate.note_id, &candidate.relative_path);
        if candidate.is_context {
            if let Some(duplicate_path) = context_paths_by_signature.get(&candidate.identity) {
                issues.push(issue(
                    candidate,
                    format!(
                        "DUPLICATE_CONTEXT_CONTENT: canonical scope identity and content hash also belong to {duplicate_path}"
                    ),
                ));
                continue;
            }
            context_paths_by_signature.insert(&candidate.identity, &candidate.relative_path);
        }
        valid_indices.push(candidate_index);
    }

    let context_indices_by_id: HashMap<&str, usize> = valid_indices
        .iter()
        .copied()
        .filter(|index| candidates[*index].is_context)
        .map(|index| (candidates[index].note_id.as_str(), index))
        .collect();
    let invalid_reasons =
        invalid_supersede_reasons(candidates, &valid_indices, &context_indices_by_id);

    if invalid_reasons.is_empty() {
        return ContextReindexManifestResult {
            accepted_indices: valid_indices,
            issues,
        };
    }

    let mut accepted_indices = Vec::with_capacity(valid_indices.len());
    for candidate_index in valid_indices {
        let candidate = &candidates[candidate_index];
        if let Some(reason) = invalid_reasons.get(candidate.note_id.as_str()) {
            issues.push(issue(candidate, format!("INVALID_SUPERSEDE: {reason}")));
        } else {
            accepted_indices.push(candidate_index);
        }
    }
    ContextReindexManifestResult {
        accepted_indices,
        issues,
    }
}

fn colliding_canonical_paths(candidates: &[ContextReindexManifestCandidate]) -> HashSet<&str> {
    let mut counts: HashMap<&str, usize> = HashMap::new();
    for candidate in candidates {
        *counts
            .entry(candidate.canonical_relative_path.as_str())
            .or_default() += 1;
    }
    counts
        .into_iter()
        .filter_map(|(path, count)| (count > 1).then_some(path))
        .collect()
}

fn invalid_supersede_reasons<'a>(
    candidates: &'a [ContextReindexManifestCandidate],
    valid_indices: &[usize],
    context_indices_by_id: &HashMap<&'a str, usize>,
) -> HashMap<&'a str, String> {
    let mut invalid_reasons = HashMap::new();
    let mut replacements_by_target: HashMap<&str, &str> = HashMap::new();

    for candidate_index in valid_indices.iter().copied() {
        let candidate = &candidates[candidate_index];
        if !candidate.is_context {
            continue;
        }
        let context_id = candidate.note_id.as_str();
        if let Some(target) = candidate.supersedes_context_id.as_deref() {
            let Some(target_index) = context_indices_by_id.get(target).copied() else {
                invalid_reasons.insert(
                    context_id,
                    format!("superseded Context is absent or invalid: {target}"),
                );
                continue;
            };
            if let Some(prior_replacement) = replacements_by_target.get(target) {
                invalid_reasons.insert(
                    context_id,
                    format!("Context already has another replacement: {prior_replacement}"),
                );
                continue;
            }
            if let Some(target_backlink) =
                candidates[target_index].superseded_by_context_id.as_deref()
                && target_backlink != context_id
            {
                invalid_reasons.insert(
                    context_id,
                    format!(
                        "superseded Context backlink conflicts with replacement: {target_backlink}"
                    ),
                );
                continue;
            }
            replacements_by_target.insert(target, context_id);
        }

        let Some(replacement) = candidate.superseded_by_context_id.as_deref() else {
            continue;
        };
        let Some(replacement_index) = context_indices_by_id.get(replacement).copied() else {
            invalid_reasons.insert(
                context_id,
                format!("replacement Context is absent or invalid: {replacement}"),
            );
            continue;
        };
        if candidates[replacement_index]
            .supersedes_context_id
            .as_deref()
            != Some(context_id)
        {
            invalid_reasons.insert(
                context_id,
                format!(
                    "replacement Context does not contain the reciprocal supersedes reference: {replacement}"
                ),
            );
        }
    }

    for context_id in cyclic_supersede_ids(candidates, valid_indices, context_indices_by_id) {
        invalid_reasons.insert(
            context_id,
            "supersede relationship contains a cycle".to_owned(),
        );
    }
    propagate_invalid_targets(
        candidates,
        valid_indices,
        context_indices_by_id,
        &mut invalid_reasons,
    );
    invalid_reasons
}

fn cyclic_supersede_ids<'a>(
    candidates: &'a [ContextReindexManifestCandidate],
    valid_indices: &[usize],
    context_indices_by_id: &HashMap<&'a str, usize>,
) -> HashSet<&'a str> {
    let mut cyclic_ids = HashSet::new();
    let mut completed_ids = HashSet::new();

    for candidate_index in valid_indices.iter().copied() {
        let candidate = &candidates[candidate_index];
        if !candidate.is_context || completed_ids.contains(candidate.note_id.as_str()) {
            continue;
        }
        let mut path = Vec::new();
        let mut positions = HashMap::new();
        let mut current_id = Some(candidate.note_id.as_str());
        while let Some(context_id) = current_id {
            if !context_indices_by_id.contains_key(context_id) {
                break;
            }
            if let Some(cycle_start) = positions.get(context_id).copied() {
                cyclic_ids.extend(path[cycle_start..].iter().copied());
                break;
            }
            if completed_ids.contains(context_id) {
                break;
            }
            positions.insert(context_id, path.len());
            path.push(context_id);
            let index = context_indices_by_id[context_id];
            current_id = candidates[index].supersedes_context_id.as_deref();
        }
        completed_ids.extend(path);
    }
    cyclic_ids
}

fn propagate_invalid_targets<'a>(
    candidates: &'a [ContextReindexManifestCandidate],
    valid_indices: &[usize],
    context_indices_by_id: &HashMap<&'a str, usize>,
    invalid_reasons: &mut HashMap<&'a str, String>,
) {
    let mut predecessors_by_target: HashMap<&str, Vec<&str>> = HashMap::new();
    for candidate_index in valid_indices.iter().copied() {
        let candidate = &candidates[candidate_index];
        if !candidate.is_context {
            continue;
        }
        if let Some(target) = candidate.supersedes_context_id.as_deref()
            && context_indices_by_id.contains_key(target)
        {
            predecessors_by_target
                .entry(target)
                .or_default()
                .push(candidate.note_id.as_str());
        }
    }

    let mut queue: VecDeque<&str> = invalid_reasons.keys().copied().collect();
    while let Some(invalid_target) = queue.pop_front() {
        let Some(predecessors) = predecessors_by_target.get(invalid_target) else {
            continue;
        };
        for predecessor in predecessors {
            if invalid_reasons.contains_key(predecessor) {
                continue;
            }
            invalid_reasons.insert(
                predecessor,
                format!("superseded Context is absent or invalid: {invalid_target}"),
            );
            queue.push_back(predecessor);
        }
    }
}

fn issue(
    candidate: &ContextReindexManifestCandidate,
    message: String,
) -> ContextReindexManifestIssue {
    ContextReindexManifestIssue {
        relative_path: candidate.relative_path.clone(),
        context_id: candidate.note_id.clone(),
        message,
    }
}
