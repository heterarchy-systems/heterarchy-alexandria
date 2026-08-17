---
title: GPT OAuth Librarian Bootstrap
status: implemented
created: 2026-05-26
updated: 2026-05-26
owner: heterarchy-alexandria
scope: obsidian-librarian
---

# GPT OAuth Librarian Bootstrap

## Goal

Make the Obsidian → Alexandria → GPT OAuth librarian path usable with stable
human-facing names:

- provider alias: `codex-oauth`
- profile aliases: `research-critic`, `obsidian-librarian`, `graph-curator`

## Delivery

- Add alias resolution for provider/profile references used by API workflows.
- Add a CLI bootstrap command that creates or verifies the default provider and
  profiles.
- Keep OAuth credentials out of Obsidian and out of CLI output.
- Preserve `GUIDANCE_ONLY` fallback when OAuth credentials are unavailable.

## Files

- `01-alias-contract.md`
- `02-bootstrap-cli.md`
- `03-verification.md`
