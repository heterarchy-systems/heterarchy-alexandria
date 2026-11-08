# Alexandria ChatGPT plugin

Private account/workspace plugin for the existing Alexandria MCP service.
The account package binds to the web-created Alexandria MCP app through
`.app.json`. The connected app owns the endpoint and OAuth dynamic registration.
This package does not deploy or restart the server or contain credentials.

The original 0.1.0 archive with a direct `mcp.json` was classified as desktop-only
by ChatGPT. A visible skill or MCP declaration did not establish a web connection.
Version 0.1.1 uses the app binding for web/mobile tool delivery. Account OAuth
consent and actual tool invocation remain separate verification steps.

## Build

From the repository root, run:

```sh
bash plugins/heterarchy-alexandria/build.sh
```

The ZIP is written under `dist/`. The seven canonical skill directories are
copied from `skills_alexandria/`; do not maintain a second source copy here.
Packaging renames `safe-markdown-storage` to its declared skill name,
`alexandria-safe-markdown-storage`, and updates relative links in the archive.
Skill bodies and invocation policies otherwise remain unchanged.

Update the existing private plugin `plugins_6adb16ec839c819186c3052c55c7daaa`
through Plugin Creator with its current release guard instead of creating a
duplicate. For the 0.1.0 migration, remove the saved `mcp.json` and `.mcp.json`
and remove `mcpServers` from the compatibility manifest in the same update;
otherwise a partial archive retains the obsolete desktop MCP declaration.
Preserve the saved presentation and generated author metadata in updates.
Account registration is separate from OAuth connection
and successful tool invocation. Inspect any component diagnostics after upload.

## Connection verification

Verify the actual local `/connect/status` and public OAuth discovery before
changing the endpoint. The configured public service requires OAuth; an
unauthenticated `/mcp` response of 401 is expected. Reuse the existing connection
where the host supports it. Otherwise complete the host's OAuth connection flow.
Keep credentials and pairing codes outside the package and chat.

The web-created app is `asdk_app_6adcf19bdbec8191bfe28adae7ae0877` and its
connection plugin is `plugin_asdk_app_6adcf19bdbec8191bfe28adae7ae0877`.
It connects to `https://skyalxandria.store/mcp` with `alexandria:mcp` and
`offline_access`. The Alexandria skill bundle references this same app, so
the host can reuse one OAuth connection.

After connection, invoke a registered read-only tool. Report transport success
separately from operational readiness and missing capabilities. Never run a
write, rebuild, or recovery operation merely to test the plugin.
