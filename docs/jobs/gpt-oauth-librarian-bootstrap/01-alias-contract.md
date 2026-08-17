---
title: Provider and Profile Alias Contract
status: implemented
created: 2026-05-26
updated: 2026-05-26
owner: heterarchy-alexandria
scope: librarian-routing
---

# Provider and Profile Alias Contract

## Contract

External callers may supply either internal IDs or unique names for these fields:

- `provider_id`
- `librarian_profile_id`
- OAuth lifecycle provider path segment

## Resolution order

1. Try the internal persisted ID.
2. Fall back to exact `name` match from repository `list_all()`.
3. Return the existing not-found error if neither matches.

## Invariant

Responses still expose canonical persisted IDs for execution evidence, selected
profiles, delegate provider IDs, and OAuth `provider_id`.
