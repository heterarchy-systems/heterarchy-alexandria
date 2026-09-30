---
name: connection-hub
description: Use when connecting or repairing an MCP client through Alexandria's local connection hub and verifying the actual configured endpoint.
---

# Connection Hub

Use the local `/connect` hub and its typed status/API responses. Keep pairing
codes and credentials out of notes, chat, logs, and source files. Do not change
credentials, tunnels, backend processes, or restart services unless the task
explicitly authorizes that action.

## Read the configured endpoint first

Use the actual configured backend origin supplied by the running service or task
environment. Do not assume `127.0.0.1:8000` or any other port.

Read:

- `GET <actual-origin>/health/live`
- `GET <actual-origin>/connect/status`
- `GET <actual-origin>/operations/readiness`

The connection status response is authoritative for `app_env`, `mcp_auth_mode`,
`mcp_endpoint`, `mcp_oauth_enabled`, `mcp_oauth_issuer`, and `local_only`. Use
the returned `mcp_endpoint` exactly when registering the client.

For local OAuth, require `mcp_auth_mode=local_oauth2`,
`mcp_oauth_enabled=true`, and `local_only=true` before generating a pairing
code. A public deployment must use its configured HTTPS issuer/resource origin;
never publish a localhost endpoint as the remote registration endpoint.

## Pair and inspect the client

Open `GET <actual-origin>/connect` on the local machine. Generate a single code
with `POST <actual-origin>/connect/mcp/pairing-code`, enter it only in the local
approval page, and poll:

- `GET <actual-origin>/connect/status`
- `GET <actual-origin>/connect/mcp/clients`
- `GET <actual-origin>/operations/readiness`

The pairing response contains `code` and aware `expires_at`. Client records
contain public-safe `client_id`, `client_name`, `status`, `connected`, `scopes`,
`resource`, token expiry timestamps, and token-family count; they do not expose
token material. Disconnect and extension are explicit POST operations at
`/connect/mcp/clients/{client_id}/disconnect` and
`/connect/mcp/clients/{client_id}/extend`.

Generate a new code only after the previous one expired or was consumed. Do not
paste a code into an unrelated endpoint or expose it through a log.

## Verify delivery separately

Health, readiness, the local page, and MCP tool discovery prove server-side
configuration only. They do not prove that the intended external provider can
invoke the registered MCP endpoint. After authorization, verify the actual
client can discover and invoke a safe registered tool through the endpoint
reported by `/connect/status`. Keep provider-delivery or transport failures
separate from core-memory readiness.

Never infer success from browser state alone, and never force a fixed port or
replace the configured endpoint with a guessed URL.
