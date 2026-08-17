---
alexandria_type: job_plan
id: job_obsidian_graph_langgraph_librarian_04_oauth_delegation_provider_routing
tags:
  - oauth
  - provider
  - librarian
  - security
status: implemented
created_at: "2026-05-26"
source: codex
---

# OAuth Delegation and Provider Routing

## 목표

Obsidian 사서창에서 OAuth로 연결된 외부 사서 provider를 선택적으로 호출할 수 있게 한다.

## 원칙

- OAuth token은 Obsidian에 저장하지 않는다.
- Obsidian plugin은 provider id/profile id/delegate flag만 backend로 보낸다.
- 실제 token resolution과 refresh는 backend provider secret store가 담당한다.
- 외부 위임은 사용자 명시 동의 또는 profile policy가 있을 때만 수행한다.

## 현재 연결할 개념

이미 존재하는 backend 개념:

```text
librarian providers
librarian profiles
OAuth start/poll/status/refresh
OpenAI/Codex OAuth adapter
librarian ask/delegate routes
```

Obsidian ask에 추가할 입력:

```json
{
  "query": "...",
  "active_note_path": "START_HERE.md",
  "delegate_to_librarian": true,
  "provider_id": "codex-oauth",
  "profile_id": "research-critic",
  "save_transcript": false
}
```

## Provider routing

routing 우선순위:

1. plugin에서 명시한 `provider_id` + `profile_id`.
2. active note/project에 지정된 preferred librarian profile.
3. backend default librarian profile.
4. local-only fallback.

## LangGraph node

```text
maybe_delegate
  input: query, local sources, provider/profile preference
  if delegate_to_librarian false:
    skip
  if provider disconnected:
    return action_required: connect_provider
  if token expired:
    refresh through backend
  call provider delegate
  sanitize response
  return delegate_result + source refs
```

## 보안 경계

Obsidian plugin에 저장 가능:

```text
apiUrl
operatorApiKey optional only if user manually sets it
defaultProject
autoSaveTranscripts
preferredProviderId optional
preferredProfileId optional
```

Obsidian plugin에 저장 금지:

```text
OAuth access token
OAuth refresh token
device code
client secret
raw provider credential
```

Markdown 저장 금지:

```text
raw token
provider secret
full private chat logs without explicit save
```

## UX

Plugin settings:

```text
Alexandria API URL: http://127.0.0.1:8000
Default project: heterarchy-alexandria
Default provider: Codex OAuth / none
Default profile: Research Critic / Skill Curator / none
Auto-save transcripts: off
```

Pane controls:

```text
[ ] Ask connected OAuth librarian
Provider: <select>
Profile: <select>
```

## Failure behavior

- provider disconnected: local answer + “Connect OAuth provider” action.
- token refresh failed: local answer + reconnect instruction.
- external provider timeout: local answer + retry action.
- operator key missing for protected action: show backend error, do not store token in plugin automatically.

## 완료 기준

- Obsidian plugin can list provider/profile options without exposing secrets.
- `delegate_to_librarian=true` routes through backend provider delegation.
- OAuth token never appears in Obsidian vault or plugin `data.json`.
- external failure degrades to local answer.

## 2026-05-26 implementation update

G003 wired approved OAuth delegation to the existing GPT/Codex librarian provider path:

- `ask_oauth_librarian` is only executed after workflow resume approval.
- The node calls `HermesCollaborationService.ask_librarian`, which routes to configured librarian profiles and OpenAI/Codex OAuth providers.
- Delegate summaries are appended to the workflow answer under `## GPT OAuth Librarian`.
- Missing provider/profile rows degrade to `GUIDANCE_ONLY`; OAuth tokens never enter Obsidian Markdown or plugin settings.
