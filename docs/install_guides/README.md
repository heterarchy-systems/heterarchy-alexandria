# Install guides

heterarchy-alexandria now supports backend/CLI/MCP setup only. The old web frontend runtime has been removed.

## Supported modes

| Mode | Use when | Requirements |
|---|---|---|
| `backend-daemon` | local PostgreSQL-backed backend for MCP agents | Python/uv/PostgreSQL |
| `guidebook-only` | planning an install without writing runtime files | none |

## Obsidian choices

| Vault shape | Setup flags |
|---|---|
| Generated vault | set `SERVICE_OBSIDIAN_VAULT_PATH` and run `POST /obsidian/init` |
| Existing vault named `Alexandria` | set `SERVICE_OBSIDIAN_VAULT_PATH` and `SERVICE_ALEXANDRIA_OBSIDIAN_ROOT=.` |

Use root `.` when the vault itself is the Alexandria workspace. Otherwise Alexandria creates/manages an `Alexandria/` folder inside the vault.

Active install guides are maintained in English and Korean. The Japanese and Chinese pages are currently unmaintained placeholders until real translations are added.
