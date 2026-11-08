# Feature settings

Each `{feature}_settings.env` belongs to the corresponding Config module:

| File | Configuration |
| --- | --- |
| `app_settings.env` | Application identity, build metadata, encryption key, readiness canary and skill root |
| `mcp_settings.env` | Public MCP auth/transport and the separate MCP backend API client |
| `memory_settings.env` | Embedding provider/recovery and model artifact acquisition |
| `vault_settings.env` | Vault paths and graph projection integrity freshness |
| `database_settings.env` | PostgreSQL connection URL |
| `redis_settings.env` | Redis caching/rate limits and maintenance queue/worker settings |

Copy each `*_settings.env.example` to the same filename without `.example`, then
edit deployment values. Actual
`*_settings.env` files are private and excluded from Git; never commit secrets.
No field has an automatic default. Missing keys fail validation; nullable values
must be explicitly written as `null`.

Config loading reads only its matching feature file. Checkout-local files are
followed by parent/current working-directory `module_setting_envs/` files; process
environment variables take precedence. The root `.env` is not a Config fallback.
Run installed commands from the repository root or `backend/`, or supply the
required process environment. Docker Compose mounts this directory read-only at `/module_setting_envs` and
Config models read their own files directly, rather than injecting file values
over image-baked build provenance or baking credentials into an image.

Redis cache and maintenance queue share one `SERVICE_REDIS_URL` value. API-only
CLI commands load only the backend API fields from `mcp_settings.env`.
