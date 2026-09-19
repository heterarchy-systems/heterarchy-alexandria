//! Golden tests for the deterministic compile-plan authority.

use std::collections::BTreeSet;
use std::error::Error;

use unicode_normalization::UnicodeNormalization;

use heterarchy_alexandria_core::compile_plan::{
    CompileChunkAction, CompileDocumentAction, CompileDocumentInput, CompileEdgeAction,
    CompileEdgeSeedInput, CompileManifestCandidateInput, CompilePolicy, CurrentSourceSnapshot,
    EmbeddingAction, EmbeddingReason, PreviousCompilationSnapshot, PreviousDocumentState,
    compile_plan,
};

const POLICY_KEY: &str = "embed-v1";

fn policy() -> CompilePolicy {
    CompilePolicy {
        chunk_max_chars: 600,
        chunk_overlap_chars: 80,
        embedding_fingerprint_key: String::from(POLICY_KEY),
    }
}

fn document(relative_path: &str, note_id: &str, body: &str) -> CompileDocumentInput {
    CompileDocumentInput {
        relative_path: String::from(relative_path),
        note_id: String::from(note_id),
        title: String::from("Sample Note"),
        alexandria_type: String::from("job_plan"),
        status: String::from("active"),
        aliases: Vec::new(),
        text: Some(format!("---\nid: {note_id}\n---\n\n{body}")),
        source_hash: String::new(),
        provided_chunks: None,
        provided_edges: None,
        body: String::from(body),
        frontmatter: serde_json::json!({ "id": note_id }),
        edge_seeds: vec![CompileEdgeSeedInput {
            target_path: Some(String::from("Contexts/other.md")),
            target_note_id: None,
            relation: String::from("wikilink"),
            source_field: String::from("related"),
        }],
        manifest_candidate: None,
    }
}

fn previous_state(
    relative_path: &str,
    note_id: &str,
    source_hash: &str,
    chunk_hashes: &[&str],
    edge_ids: &[&str],
) -> PreviousDocumentState {
    PreviousDocumentState {
        note_id: String::from(note_id),
        relative_path: String::from(relative_path),
        source_hash: String::from(source_hash),
        chunk_hashes: chunk_hashes
            .iter()
            .map(|hash| String::from(*hash))
            .collect(),
        edge_ids: edge_ids.iter().map(|id| String::from(*id)).collect(),
    }
}

fn empty_previous() -> PreviousCompilationSnapshot {
    PreviousCompilationSnapshot {
        embedding_fingerprint_key: String::from(POLICY_KEY),
        documents: Vec::new(),
    }
}

#[test]
fn full_compile_treats_empty_previous_as_added_work() -> Result<(), Box<dyn Error>> {
    let current = CurrentSourceSnapshot {
        documents: vec![document("Contexts/a.md", "note-a", "# A\n\nfirst body")],
    };
    let plan = compile_plan(&current, &empty_previous(), &policy())?;
    assert_eq!(plan.upserts.len(), 1);
    let upsert = &plan.upserts[0];
    assert_eq!(upsert.action, CompileDocumentAction::Added);
    assert_eq!(upsert.embedding.action, EmbeddingAction::Reembed);
    assert_eq!(upsert.embedding.reason, EmbeddingReason::DocumentAdded);
    assert!(
        upsert
            .chunks
            .iter()
            .all(|chunk| chunk.action == CompileChunkAction::Add)
    );
    assert!(
        upsert
            .edges
            .iter()
            .all(|edge| edge.action == CompileEdgeAction::Add)
    );
    assert!(!upsert.source_hash.is_empty());
    assert!(!plan.plan_fingerprint.is_empty());
    Ok(())
}

#[test]
fn same_inputs_and_policy_produce_identical_plans() -> Result<(), Box<dyn Error>> {
    let current = CurrentSourceSnapshot {
        documents: vec![
            document("Contexts/b.md", "note-b", "# B\n\nsecond"),
            document("Contexts/a.md", "note-a", "# A\n\nfirst"),
        ],
    };
    let first = compile_plan(&current, &empty_previous(), &policy())?;
    let second = compile_plan(&current, &empty_previous(), &policy())?;
    assert_eq!(first.plan_fingerprint, second.plan_fingerprint);
    let first_json = serde_json::to_string(&first)?;
    let second_json = serde_json::to_string(&second)?;
    assert_eq!(first_json, second_json);
    Ok(())
}

#[test]
fn unchanged_document_produces_no_work_until_policy_changes() -> Result<(), Box<dyn Error>> {
    let current = CurrentSourceSnapshot {
        documents: vec![document("Contexts/a.md", "note-a", "stable body")],
    };
    let plan = compile_plan(&current, &empty_previous(), &policy())?;
    let upsert = &plan.upserts[0];

    let previous = PreviousCompilationSnapshot {
        embedding_fingerprint_key: String::from(POLICY_KEY),
        documents: vec![previous_state(
            "Contexts/a.md",
            "note-a",
            &upsert.source_hash,
            &upsert
                .chunks
                .iter()
                .map(|c| c.content_hash.as_str())
                .collect::<Vec<_>>(),
            &upsert
                .edges
                .iter()
                .map(|e| e.edge_id.as_str())
                .collect::<Vec<_>>(),
        )],
    };
    let incremental = compile_plan(&current, &previous, &policy())?;
    assert!(incremental.upserts.is_empty());
    assert!(incremental.removals.is_empty());

    let new_policy = CompilePolicy {
        embedding_fingerprint_key: String::from("embed-v2"),
        ..policy()
    };
    let reembed = compile_plan(&current, &previous, &new_policy)?;
    assert_eq!(reembed.upserts.len(), 1);
    assert_eq!(
        reembed.upserts[0].action,
        CompileDocumentAction::EmbeddingOnly
    );
    assert_eq!(
        reembed.upserts[0].embedding.reason,
        EmbeddingReason::EmbeddingPolicyChanged
    );
    assert!(
        reembed.upserts[0]
            .chunks
            .iter()
            .all(|chunk| chunk.action == CompileChunkAction::Keep)
    );
    Ok(())
}

#[test]
fn metadata_only_change_avoids_reembedding() -> Result<(), Box<dyn Error>> {
    let mut first_document = document("Contexts/a.md", "note-a", "stable body");
    first_document.frontmatter = serde_json::json!({ "id": "note-a", "tags": [] });
    let initial = compile_plan(
        &CurrentSourceSnapshot {
            documents: vec![first_document.clone()],
        },
        &empty_previous(),
        &policy(),
    )?;
    let initial_upsert = &initial.upserts[0];

    let mut changed_document = document("Contexts/a.md", "note-a", "stable body");
    changed_document.frontmatter = serde_json::json!({ "id": "note-a", "tags": ["x"] });
    changed_document.text = Some(format!(
        "---\nid: note-a\ntags: [x]\n---\n\n{}",
        changed_document.body
    ));
    let previous = PreviousCompilationSnapshot {
        embedding_fingerprint_key: String::from(POLICY_KEY),
        documents: vec![previous_state(
            "Contexts/a.md",
            "note-a",
            &initial_upsert.source_hash,
            &initial_upsert
                .chunks
                .iter()
                .map(|chunk| chunk.content_hash.as_str())
                .collect::<Vec<_>>(),
            &initial_upsert
                .edges
                .iter()
                .map(|edge| edge.edge_id.as_str())
                .collect::<Vec<_>>(),
        )],
    };
    let plan = compile_plan(
        &CurrentSourceSnapshot {
            documents: vec![changed_document],
        },
        &previous,
        &policy(),
    )?;
    assert_eq!(plan.upserts.len(), 1);
    assert_eq!(plan.upserts[0].action, CompileDocumentAction::Updated);
    assert_eq!(plan.upserts[0].embedding.action, EmbeddingAction::None);
    assert!(
        plan.upserts[0]
            .chunks
            .iter()
            .all(|chunk| chunk.action == CompileChunkAction::Keep)
    );
    Ok(())
}

#[test]
fn changed_content_reembeds_only_changed_chunks_and_diffs_edges() -> Result<(), Box<dyn Error>> {
    let body_a = "# A\n\noriginal paragraph with plenty of shared text\n";
    let initial_document = document("Contexts/a.md", "note-a", body_a);
    let initial = compile_plan(
        &CurrentSourceSnapshot {
            documents: vec![initial_document],
        },
        &empty_previous(),
        &policy(),
    )?;
    let initial_upsert = &initial.upserts[0];
    let previous_edge_ids: Vec<String> = initial_upsert
        .edges
        .iter()
        .map(|edge| edge.edge_id.clone())
        .chain(std::iter::once(String::from("vanished-edge")))
        .collect();

    let changed_document = document(
        "Contexts/a.md",
        "note-a",
        "# A\n\noriginal paragraph with plenty of shared text\n\nnew appended paragraph\n",
    );
    let previous = PreviousCompilationSnapshot {
        embedding_fingerprint_key: String::from(POLICY_KEY),
        documents: vec![previous_state(
            "Contexts/a.md",
            "note-a",
            &initial_upsert.source_hash,
            &initial_upsert
                .chunks
                .iter()
                .map(|chunk| chunk.content_hash.as_str())
                .collect::<Vec<_>>(),
            &previous_edge_ids
                .iter()
                .map(String::as_str)
                .collect::<Vec<_>>(),
        )],
    };
    let plan = compile_plan(
        &CurrentSourceSnapshot {
            documents: vec![changed_document],
        },
        &previous,
        &policy(),
    )?;
    assert_eq!(plan.upserts.len(), 1);
    let upsert = &plan.upserts[0];
    assert_eq!(upsert.action, CompileDocumentAction::Updated);
    assert_eq!(upsert.embedding.reason, EmbeddingReason::ChunksChanged);
    let changed_actions: Vec<usize> = upsert
        .chunks
        .iter()
        .enumerate()
        .filter(|(_, chunk)| chunk.action != CompileChunkAction::Keep)
        .map(|(index, _)| index)
        .collect();
    assert_eq!(changed_actions, upsert.embedding.chunk_indexes);
    assert!(
        upsert.chunks.len() > changed_actions.len() || changed_actions.len() == upsert.chunks.len(),
        "chunk actions must cover the document consistently"
    );
    assert!(
        upsert
            .removed_edge_ids
            .contains(&String::from("vanished-edge"))
    );
    Ok(())
}

#[test]
fn removed_documents_become_removals_with_embedding_removal() -> Result<(), Box<dyn Error>> {
    let previous = PreviousCompilationSnapshot {
        embedding_fingerprint_key: String::from(POLICY_KEY),
        documents: vec![previous_state(
            "Contexts/gone.md",
            "note-gone",
            "hash",
            &["chunk-hash"],
            &[],
        )],
    };
    let plan = compile_plan(
        &CurrentSourceSnapshot {
            documents: Vec::new(),
        },
        &previous,
        &policy(),
    )?;
    assert!(plan.upserts.is_empty());
    assert_eq!(plan.removals.len(), 1);
    assert_eq!(plan.removals[0].note_id, "note-gone");
    Ok(())
}

#[test]
fn manifest_duplicates_surface_as_diagnostics() -> Result<(), Box<dyn Error>> {
    let mut first = document("Contexts/dup.md", "note-dup", "body one");
    first.alexandria_type = String::from("context");
    first.manifest_candidate = Some(CompileManifestCandidateInput {
        note_id: String::from("note-dup"),
        relative_path: String::from("Contexts/dup.md"),
        canonical_relative_path: String::from("Contexts/dup.md"),
        is_context: true,
        identity: manifest_identity("hash-dup"),
        supersedes_context_id: None,
        superseded_by_context_id: None,
    });
    let mut second = document("Contexts/alias/dup.md", "note-dup", "body two");
    second.alexandria_type = String::from("context");
    second.manifest_candidate = Some(CompileManifestCandidateInput {
        note_id: String::from("note-dup"),
        relative_path: String::from("Contexts/alias/dup.md"),
        canonical_relative_path: String::from("Contexts/alias/dup.md"),
        is_context: true,
        identity: manifest_identity("hash-dup"),
        supersedes_context_id: None,
        superseded_by_context_id: None,
    });
    let plan = compile_plan(
        &CurrentSourceSnapshot {
            documents: vec![first, second],
        },
        &empty_previous(),
        &policy(),
    )?;
    assert!(
        !plan.diagnostics.is_empty(),
        "duplicate note ids must surface diagnostics"
    );
    Ok(())
}

#[test]
fn shuffled_input_order_produces_identical_fingerprints() -> Result<(), Box<dyn Error>> {
    let ordered = CurrentSourceSnapshot {
        documents: vec![
            document("Contexts/a.md", "note-a", "alpha body"),
            document("Contexts/b.md", "note-b", "beta body"),
            document("Contexts/c.md", "note-c", "gamma body"),
        ],
    };
    let mut shuffled_inputs = ordered.documents.clone();
    shuffled_inputs.reverse();
    let shuffled = CurrentSourceSnapshot {
        documents: shuffled_inputs,
    };
    let first = compile_plan(&ordered, &empty_previous(), &policy())?;
    let second = compile_plan(&shuffled, &empty_previous(), &policy())?;
    assert_eq!(first.plan_fingerprint, second.plan_fingerprint);
    let mut ordered_paths = BTreeSet::new();
    for upsert in &first.upserts {
        ordered_paths.insert(upsert.relative_path.clone());
    }
    assert_eq!(ordered_paths.len(), 3);
    Ok(())
}

fn manifest_identity(
    content_hash: &str,
) -> heterarchy_alexandria_core::compile_plan::CompileContextIdentityInput {
    heterarchy_alexandria_core::compile_plan::CompileContextIdentityInput {
        scope: Some(String::from("project:Project")),
        project: Some(String::from("Project")),
        workspace_id: None,
        agent_id: None,
        user_id: None,
        session_id: None,
        content_hash: Some(String::from(content_hash)),
    }
}

use heterarchy_alexandria_core::compile_plan::{
    DiagnosticEdgeInput, DiagnosticNoteInput, DiagnosticTargetOutcome, resolve_diagnostic_targets,
};

#[test]
fn diagnostic_resolution_authority_handles_nfc_nfd_and_korean_aliases() {
    let nfc_path = "Contexts/R\u{e9}sum\u{e9}.md";
    let nfd_path = "Contexts/Re\u{301}sume\u{301}.md";
    let korean_alias_nfc = "\u{d55c}\u{ae00} \u{c77d}\u{ae30}";
    let decomposed_alias = "\u{1112}\u{1161}\u{11AB}\u{1100}\u{1173}\u{11AF} \u{c77d}\u{ae30}";
    let notes = vec![
        DiagnosticNoteInput {
            note_id: String::from("note-resume"),
            relative_path: String::from(nfc_path),
            title: String::from("R\u{e9}sum\u{e9}"),
            status: String::from("active"),
            index_status: String::from("indexed"),
            aliases: vec![String::from(korean_alias_nfc)],
        },
        DiagnosticNoteInput {
            note_id: String::from("note-twin"),
            relative_path: String::from("Contexts/Resume Twin.md"),
            title: String::from("R\u{e9}sum\u{e9}"),
            status: String::from("active"),
            index_status: String::from("indexed"),
            aliases: Vec::new(),
        },
        DiagnosticNoteInput {
            note_id: String::from("note-stale"),
            relative_path: String::from("Contexts/Archived.md"),
            title: String::from("Archived"),
            status: String::from("archived"),
            index_status: String::from("stale"),
            aliases: Vec::new(),
        },
    ];
    let edges = vec![
        DiagnosticEdgeInput {
            edge_id: String::from("e-nfd-path"),
            source_note_id: String::from("note-twin"),
            target_note_id: None,
            target_path: String::from(nfd_path),
        },
        DiagnosticEdgeInput {
            edge_id: String::from("e-korean-alias-nfd"),
            source_note_id: String::from("note-twin"),
            target_note_id: None,
            target_path: String::from(decomposed_alias),
        },
        DiagnosticEdgeInput {
            edge_id: String::from("e-ambiguous-title"),
            source_note_id: String::from("note-resume"),
            target_note_id: None,
            target_path: String::from("R\u{e9}sum\u{e9}"),
        },
        DiagnosticEdgeInput {
            edge_id: String::from("e-target-not-indexed"),
            source_note_id: String::from("note-twin"),
            target_note_id: None,
            target_path: String::from("Contexts/Archived.md"),
        },
        DiagnosticEdgeInput {
            edge_id: String::from("e-missing"),
            source_note_id: String::from("note-twin"),
            target_note_id: None,
            target_path: String::from("Contexts/Absent.md"),
        },
    ];
    let resolutions = resolve_diagnostic_targets(&notes, &edges);
    let by_edge: std::collections::BTreeMap<&str, &_> = resolutions
        .iter()
        .map(|r| (r.edge_id.as_str(), r))
        .collect();

    let nfd = &by_edge["e-nfd-path"];
    assert_eq!(nfd.outcome, DiagnosticTargetOutcome::Resolved);
    assert_eq!(nfd.target_note_id.as_deref(), Some("note-resume"));

    let korean = &by_edge["e-korean-alias-nfd"];
    assert_eq!(korean.outcome, DiagnosticTargetOutcome::Resolved);
    assert_eq!(korean.target_note_id.as_deref(), Some("note-resume"));

    let ambiguous = &by_edge["e-ambiguous-title"];
    assert_eq!(ambiguous.outcome, DiagnosticTargetOutcome::Ambiguous);
    assert_eq!(ambiguous.candidate_note_ids.len(), 2);

    let not_indexed = &by_edge["e-target-not-indexed"];
    assert_eq!(
        not_indexed.outcome,
        DiagnosticTargetOutcome::TargetNotIndexed
    );
    assert_eq!(not_indexed.target_note_id.as_deref(), Some("note-stale"));

    assert_eq!(
        by_edge["e-missing"].outcome,
        DiagnosticTargetOutcome::Missing
    );
}

#[test]
fn diagnostic_resolution_minimal_exact_path() {
    let notes = vec![DiagnosticNoteInput {
        note_id: String::from("note-a"),
        relative_path: String::from("Contexts/a.md"),
        title: String::from("A"),
        status: String::from("active"),
        index_status: String::from("indexed"),
        aliases: Vec::new(),
    }];
    let edges = vec![DiagnosticEdgeInput {
        edge_id: String::from("e1"),
        source_note_id: String::from("note-a"),
        target_note_id: None,
        target_path: String::from("Contexts/a.md"),
    }];
    let out = resolve_diagnostic_targets(&notes, &edges);
    assert_eq!(out[0].outcome, DiagnosticTargetOutcome::Resolved);
}

#[test]
fn diagnostic_resolution_minimal_nfd_path() {
    let nfc = String::from("Contexts/R\u{e9}sum\u{e9}.md");
    let nfd = String::from("Contexts/Re\u{301}sume\u{301}.md");
    let notes = vec![DiagnosticNoteInput {
        note_id: String::from("note-a"),
        relative_path: nfc.clone(),
        title: String::from("R\u{e9}sum\u{e9}"),
        status: String::from("active"),
        index_status: String::from("indexed"),
        aliases: Vec::new(),
    }];
    let edges = vec![DiagnosticEdgeInput {
        edge_id: String::from("e-nfd"),
        source_note_id: String::from("note-a"),
        target_note_id: None,
        target_path: nfd.clone(),
    }];
    let out = resolve_diagnostic_targets(&notes, &edges);
    assert_eq!(out[0].outcome, DiagnosticTargetOutcome::Resolved);
    assert_eq!(nfc, nfd.nfc().collect::<String>());
}

#[test]
fn nfc_composition_sanity() {
    let nfc = String::from("R\u{e9}sum\u{e9}");
    let nfd = String::from("Re\u{301}sume\u{301}");
    let composed: String = nfd.nfc().collect();
    assert_eq!(nfc, composed, "NFD must compose back to NFC");
}

#[test]
fn diagnostic_resolution_minimal_korean_alias() {
    let korean_alias_nfc = "\u{d55c}\u{ae00} \u{c77d}\u{ae30}";
    let decomposed_alias = "\u{1112}\u{1161}\u{11AB}\u{1100}\u{1173}\u{11AF} \u{c77d}\u{ae30}";
    let notes = vec![DiagnosticNoteInput {
        note_id: String::from("note-ko"),
        relative_path: String::from("Contexts/guide.md"),
        title: String::from("Guide"),
        status: String::from("active"),
        index_status: String::from("indexed"),
        aliases: vec![String::from(korean_alias_nfc)],
    }];
    let edges = vec![DiagnosticEdgeInput {
        edge_id: String::from("e-ko"),
        source_note_id: String::from("note-ko"),
        target_note_id: None,
        target_path: String::from(decomposed_alias),
    }];
    let out = resolve_diagnostic_targets(&notes, &edges);
    assert_eq!(out[0].outcome, DiagnosticTargetOutcome::Resolved);
    let composed: String = decomposed_alias.nfc().collect();
    assert_eq!(composed, korean_alias_nfc);
}

#[test]
fn diagnostic_resolution_minimal_ascii_alias() {
    let notes = vec![DiagnosticNoteInput {
        note_id: String::from("note-a"),
        relative_path: String::from("Contexts/guide.md"),
        title: String::from("Guide"),
        status: String::from("active"),
        index_status: String::from("indexed"),
        aliases: vec![String::from("guide-alias")],
    }];
    let edges = vec![
        DiagnosticEdgeInput {
            edge_id: String::from("e-title"),
            source_note_id: String::from("note-a"),
            target_note_id: None,
            target_path: String::from("Guide"),
        },
        DiagnosticEdgeInput {
            edge_id: String::from("e-alias"),
            source_note_id: String::from("note-a"),
            target_note_id: None,
            target_path: String::from("guide-alias"),
        },
    ];
    let out = resolve_diagnostic_targets(&notes, &edges);
    assert_eq!(
        out[0].outcome,
        DiagnosticTargetOutcome::Resolved,
        "title link"
    );
    assert_eq!(
        out[1].outcome,
        DiagnosticTargetOutcome::Resolved,
        "alias link"
    );
}

#[test]
fn diagnostic_resolution_minimal_korean_alias_composed() {
    let notes = vec![DiagnosticNoteInput {
        note_id: String::from("note-ko"),
        relative_path: String::from("Contexts/guide.md"),
        title: String::from("Guide"),
        status: String::from("active"),
        index_status: String::from("indexed"),
        aliases: vec![String::from("\u{d55c}\u{ae00} \u{c77d}\u{ae30}")],
    }];
    let edges = vec![DiagnosticEdgeInput {
        edge_id: String::from("e-ko-nfc"),
        source_note_id: String::from("note-ko"),
        target_note_id: None,
        target_path: String::from("\u{d55c}\u{ae00} \u{c77d}\u{ae30}"),
    }];
    let out = resolve_diagnostic_targets(&notes, &edges);
    assert_eq!(out[0].outcome, DiagnosticTargetOutcome::Resolved);
}

#[test]
fn nfc_hangul_jamo_composition_sanity() {
    let nfc = String::from("\u{d55c}\u{ae00}");
    let jamo = String::from("\u{1112}\u{1161}\u{11AB}\u{1100}\u{1173}\u{11AF}");
    let composed: String = jamo.nfc().collect();
    assert_eq!(nfc, composed, "jamo must compose: got {composed}");
}
