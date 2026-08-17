---
title: Canonical Artifact Capture Command
id: job_obsidian_canonical_artifacts_01_capture_command
tags:
  - alexandria
  - obsidian
  - cli
status: active
source: codex
---

# Canonical Artifact Capture Command

## Contract

`heterarchy-alexandria obsidian capture` is the migration-safe CLI for creating
canonical artifact notes without reviving old SQLite CRUD flows.

Supported types:

- `memory_compact`
- `skill`
- `prompt`

The command posts to the existing `/obsidian/notes` API, which writes Markdown
through a temp-file replace and immediately updates the SQLite Obsidian index.

## Defaults

Capture adds safe default tags/frontmatter:

| Type | Default tags | Default frontmatter |
| --- | --- | --- |
| `memory_compact` | `alexandria`, `memory-compact` | `artifact_kind: memory_compact`, optional coverage timestamps |
| `skill` | `alexandria`, `skill`, `draft` | `artifact_kind: skill`, `skill_status: draft`, `review_status: needs_review` |
| `prompt` | `alexandria`, `prompt`, `template` | `artifact_kind: prompt`, `prompt_kind: template` |

`--frontmatter-json` accepts a JSON object for migration metadata. It is merged
before the backend stamps canonical Alexandria fields such as `alexandria_type`,
`id`, `created_at`, `updated_at`, `status`, and `source`.

## Examples

```bash
heterarchy-alexandria obsidian capture "Browser Verification Skill" \
  --body-file ./skill.md \
  --type skill \
  --project heterarchy-alexandria \
  --tag browser

heterarchy-alexandria obsidian capture "Release Review Prompt" \
  --body-file ./prompt.md \
  --type prompt \
  --prompt-kind template \
  --frontmatter-json '{"owner":"librarian"}'
```
