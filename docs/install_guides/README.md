# Install guides

heterarchy-alexandria now supports backend/CLI/MCP setup only. The old web frontend runtime has been removed.

## Supported modes

| Mode | Use when | Requirements |
|---|---|---|
| `backend-daemon` | local backend + SQLite state for CLI/MCP agents | Python/uv |
| `guidebook-only` | planning an install without writing runtime files | none |

## Obsidian choices

| Vault shape | Setup flags |
|---|---|
| Generated vault | `heterarchy-alexandria setup --mode backend-daemon --apply --write-guidebook --run-migrations` |
| Existing vault named `Alexandria` | add `--obsidian-vault-path "$HOME/Desktop/Alexandria" --alexandria-obsidian-root "."` |

Use root `.` when the vault itself is the Alexandria workspace. Otherwise Alexandria creates/manages an `Alexandria/` folder inside the vault.

Active install guides are maintained in English and Korean. The Japanese and Chinese pages are currently unmaintained placeholders until real translations are added.
