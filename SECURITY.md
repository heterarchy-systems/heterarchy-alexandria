# Security

heterarchy-alexandria is currently a local backend/CLI/MCP service.

- The backend uses the configured operator key header for protected control-plane routes.
- Keep the backend bound to `127.0.0.1` unless a deployment explicitly requires otherwise.
- Do not commit secrets, OAuth tokens, API keys, private keys, or raw credentials.
- The removed frontend no longer proxies operator-key requests.
