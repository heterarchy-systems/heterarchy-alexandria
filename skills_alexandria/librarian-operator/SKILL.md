---
name: librarian-skill-acquisition
description: Use when an agent needs a reusable capability that is missing from Alexandria. Search existing skills first; if insufficient, start an autonomous Librarian skill-acquisition job that researches authoritative sources, drafts and validates a reusable skill, publishes it to Obsidian, and returns a handoff to the requesting agent.
---

# Librarian Skill Acquisition

Alexandria Librarian is a focused **Skill Acquisition Agent**. It is not the general vault operator, memory compactor, OAuth controller, or catch-all research assistant.

## Responsibility boundary

```text
Requesting Agent
→ search existing skills
→ reuse when sufficient
→ otherwise start acquisition
→ Librarian researches and drafts
→ validate evidence and artifact
→ publish canonical Skill to Obsidian
→ reindex / verify
→ return durable handoff
→ requesting Agent resumes work
```

Other ownership boundaries:

- Alexandria Core owns vault search, note CRUD, graph, inventory, review, and safe moves.
- Memory Steward owns reconciliation, conflicts, Memory Compact lifecycle, and periodic compaction.
- Provider selection, credentials, and OAuth are internal execution details and are not agent-facing MCP controls.

## Procedure
1. Search the existing skill library first with the narrowest capability brief that represents the task.
2. Reuse a sufficient active skill instead of starting acquisition.
3. If the best candidate is partial or absent, start one bounded acquisition job with the observed gaps and evidence requirements.
4. Poll the durable job to completion, then verify the published skill is rediscoverable before handing it back.

## Public MCP contract

### 1. Search first

Use:

- `alexandria_search_skills(capability=..., task_goal=..., project=...)`

Pass the concrete missing capability, current task goal, environment, required tools, constraints, risk tolerance, and success criteria when known.

If an existing skill is sufficient, reuse it. Do not create a duplicate acquisition job.

### 2. Start autonomous acquisition

Only when search is insufficient:

- `alexandria_start_skill_acquisition(prompt=..., project=..., search_snapshot=...)`

The requesting agent does **not** select a provider, profile, OAuth token, model, or completion route. Alexandria selects an executable provider internally and runs the acquisition job in the background.

The acquisition job should:

1. research the missing capability;
2. prefer official documentation, primary repositories, standards, and first-party examples;
3. distinguish verified behavior from inference;
4. produce claim-linked evidence;
5. draft a reusable skill with environment/tool constraints and safety notes;
6. publish the skill to canonical Obsidian storage;
7. reindex and verify the saved artifact;
8. persist a resume handoff for the requesting agent.

If evidence is insufficient, the job must become review/failed state rather than invent sources or silently activate an unverified skill.

### 3. Poll the durable job

Use:

- `alexandria_skill_acquisition_job_status(job_id=...)`

A successful terminal result should provide the durable skill handle/path, verification state, evidence references, and a concise handoff explaining how the requesting agent should resume its blocked task.

There is no public manual-completion tool. Publication and completion belong to the acquisition runner.

## Evidence and activation rule

A reusable skill should not become trusted merely because a model produced text. Require, where applicable:

- authoritative evidence references;
- current environment/version assumptions;
- required tool names;
- reproducible usage steps or examples;
- safety/risk constraints;
- duplicate search before publication;
- successful canonical save and read-back;
- index/search verification after publication.

## Alexandria Core operations

For ordinary library work, use Core tools instead of Librarian delegation:

- `alexandria_search_vault`
- `alexandria_read_note`
- `alexandria_get_related_notes`
- `alexandria_create_note`
- `alexandria_update_note`
- `alexandria_upsert_note`
- `alexandria_vault_review_queue`
- `alexandria_vault_review_move_plan`
- `alexandria_vault_review_apply_moves`
- `alexandria_vault_inventory`
- `alexandria_vault_path_search`
- `alexandria_vault_move_plan`
- `alexandria_vault_apply_moves`

Vault maintenance is not Librarian skill acquisition.

## Memory Steward boundary

Memory lifecycle is separate from the Librarian:

- temporal reconciliation and conflict handling;
- Memory Compact review/promotion/archive;
- periodic compaction;
- memory readiness and lifecycle maintenance.

A Librarian-created skill may emit durable Context/evidence that Memory Steward later compacts, but the Librarian does not own the compaction lifecycle.

## Safety

Never persist secrets, OAuth tokens, device codes, raw credentials, or transient provider logs in Skill notes or handoffs. Provider/OAuth setup belongs to the connection-management boundary, not the requesting agent.

## Source evidence
- https://github.com/heterarchy-systems/heterarchy-alexandria/blob/main/backend/app/librarian/application/skill_library/skill_library_search_service.py
- https://github.com/heterarchy-systems/heterarchy-alexandria/blob/main/backend/app/mcp_server/tools/skills/skill_acquisition_registration.py

## Related Alexandria skills

- [[Skills/Active/Alexandria Library]] — canonical search/read/write rules.
- [[Skills/Active/Alexandria Operational Sync]] — index, embedding, graph, and recovery operations.
- `skills_alexandria/safe-markdown-storage/SKILL.md` — canonical Skill/Context Markdown persistence rules.
