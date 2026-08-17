---
alexandria_type: job_plan
id: job_obsidian_alexandria_integration_02_frontmatter_contract
tags:
  - frontmatter
  - yaml
  - obsidian
  - contract
status: implemented
created_at: "2026-05-25"
source: codex
---

# Frontmatter Contract

## 원칙

Alexandria가 생성하거나 공식 검색 대상으로 승격한 Markdown은 파일 첫 줄부터 YAML frontmatter를 가져야 한다.

```md
---
alexandria_type: context
id: ctx_example
tags:
  - alexandria
status: active
created_at: "2026-05-25"
source: human
---

# Title
```

## 공통 필수 필드

```yaml
---
alexandria_type: context
id: ctx_<stable_id>
tags:
  - alexandria
  - example
status: active
created_at: "2026-05-25"
source: human
---
```

필드 의미:

- `alexandria_type`: `context`, `memory_compact`, `skill`, `prompt`, `librarian_brief`, `librarian_chat`, `job_plan` 등 note 종류.
- `id`: 파일명/폴더 이동과 무관한 stable machine id.
- `tags`: Obsidian과 Alexandria 검색이 같이 쓰는 태그.
- `status`: 일반 note는 `active`, `draft`, `archived`, `superseded`를 우선 사용한다.
- `created_at`: 문자열 날짜/시간. YAML parser 차이를 줄이기 위해 따옴표를 권장한다.
- `source`: `human`, `codex`, `mcp`, `librarian`, `obsidian-plugin`, `import`, `heterarchy-alexandria`.

## 타입별 권장 필드

### context

```yaml
alexandria_type: context
kind: decision
project: heterarchy-alexandria
scope: project
visibility: project
importance: high
updated_at: "2026-05-25"
```

`kind` 후보:

- `decision`
- `handoff`
- `bug_root_cause`
- `project_context`
- `research`
- `plan`
- `memory`

### memory_compact

현재 구현체는 uppercase enum을 사용한다. 호환을 위해 그대로 유지한다.

```yaml
alexandria_type: memory_compact
id: compact_<stable_id>
tags: [alexandria, memory-compact]
status: CURRENT
source: heterarchy-alexandria
project: heterarchy-alexandria
covered_from: "2026-05-25T00:00:00Z"
covered_to: "2026-05-25T23:59:59Z"
created_at: "2026-05-25T12:00:00Z"
updated_at: "2026-05-25T12:00:00Z"
archived_at: null
source_refs: []
```

`status` 후보:

- `DRAFT`
- `CURRENT`
- `SUPERSEDED`
- `ARCHIVED`

### skill

```yaml
alexandria_type: skill
risk_level: low
required_tools:
  - web.run
owner: human
version: "0.1.0"
```

### prompt

```yaml
alexandria_type: prompt
prompt_kind: template
model_hint: frontier
variables:
  - task
  - vault_context
version: "0.1.0"
```

### librarian_chat

```yaml
alexandria_type: librarian_chat
conversation_id: chat_20260525_001
project: heterarchy-alexandria
active_note_path: "Alexandria/Contexts/Decisions/Obsidian Storage.md"
linked_note_ids:
  - ctx_obsidian_canonical_storage
```

## import 정책

frontmatter가 없는 기존 Obsidian note:

1. 기본적으로 공식 Alexandria 자산으로 취급하지 않는다.
2. read-only 참고 검색 대상으로만 제한적으로 사용할 수 있다.
3. 사용자가 승격하거나 사서가 승격 제안한 뒤 frontmatter를 붙인다.
4. 승격 후부터 SQLite/MCP는 `alexandria_type`과 `id`를 기준으로 처리한다.

## 완료 기준

- parser가 frontmatter 없는 note를 안전하게 분리한다.
- 필수 필드 누락 시 index warning을 남긴다.
- `id` 충돌은 hard error로 보고한다.
- frontmatter update 테스트가 본문을 보존한다.
