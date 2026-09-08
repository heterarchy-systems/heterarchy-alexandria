## Summary

-

## Impacted areas

- [ ] Backend / API
- [ ] CLI / MCP
- [ ] Context Vault / RAG
- [ ] Memory Compacts
- [ ] Library skills/prompts
- [ ] Memory Steward / reconciliation
- [ ] Install / Docker / CI
- [ ] Documentation

## Validation

Paste the exact commands you ran and the result.

```text
# example
cd backend && make ci
```

## Security / privacy checklist

- [ ] I did not commit raw API keys, operator keys, OAuth tokens, provider secrets, private keys, or full unredacted conversation logs.
- [ ] I used placeholders such as `[REDACTED]` or `<operator-key>` in docs, tests, and examples.
- [ ] Any protected control-plane call uses the operator-key model, not a login/session/RBAC assumption.

## Product positioning checklist

- [ ] The change preserves heterarchy-alexandria as a local-first agent-native library/control plane.
- [ ] The change does not reposition the project as an autonomous agent runtime, prompt marketplace, MCP marketplace, or generic hosted memory API.
- [ ] User-facing copy avoids raw backend routes, source ids, or internal identifiers unless the user explicitly asked for API details.

## Risk / rollback notes

- Risk:
- Rollback:
