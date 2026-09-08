---
name: connection-hub
description: Use when connecting or repairing an MCP client through the local /connect page, including pairing-code generation and secret-safe connection verification.
---

# Connection Hub

Use Alexandria's local connection page instead of manually handling OAuth
tokens.

## Safety boundary

- Open `http://127.0.0.1:8000/connect` from the same machine as the backend.
- Do not paste access tokens, refresh tokens, device codes, or pairing codes into
  Obsidian notes, chat transcripts, logs, or source files.
- Pairing codes are short-lived and one-time use.
- Do not expose the local page publicly without HTTPS and operator
  authentication.
- Core memory and local retrieval remain usable independently of MCP client auth.

## Procedure
1. Run the preflight checks and confirm the local backend/readiness surface.
2. Start the exact MCP client connection flow.
3. Poll the returned status instead of guessing completion from browser state.
4. Finish only after the verification checks succeed; use the bounded repair path for a classified failure.

## Preflight

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/connect/status | jq
curl -fsS http://127.0.0.1:8000/operations/readiness | jq
```

Require `local_only=true`. For MCP browser authorization, require
`mcp_auth_mode=local_oauth2` and `mcp_oauth_enabled=true`.

When a public tunnel or domain fronts the local backend, configure both values
to the same stable public origin before connecting ChatGPT:

```bash
SERVICE_MCP_OAUTH_ISSUER=https://alexandria.example
SERVICE_MCP_OAUTH_RESOURCE=https://alexandria.example/mcp
```

Restart the backend and verify that protected-resource and authorization-server
metadata advertise only public HTTPS URLs. A localhost `registration_endpoint`
causes remote clients to report that RFC 7591 registration is unsupported even
when `/register` itself is implemented.

## Connect an MCP client

1. Copy the MCP Endpoint displayed by `/connect`.
2. Register that endpoint in the MCP client.
3. When the browser approval page opens, generate a one-time pairing code from
   the hub.
4. Enter the code only in the local approval page.
5. Complete OAuth authorization and verify MCP tool discovery.

Do not generate multiple codes preemptively. Generate a new code only after the
previous code expired or was consumed.

## Verification

After connection:

```bash
curl -fsS http://127.0.0.1:8000/connect/status | jq
curl -fsS http://127.0.0.1:8000/operations/readiness | jq
```

Confirm:

- no credential material appears in either response;
- core readiness remains `READY`;
- retrieval remains `HYBRID` when embeddings are healthy;
- MCP client connection failures do not disable core memory;
- the MCP client can discover Alexandria tools only after authorization.
