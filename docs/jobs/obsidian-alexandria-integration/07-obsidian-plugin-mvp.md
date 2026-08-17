---
alexandria_type: job_plan
id: job_obsidian_alexandria_integration_07_obsidian_plugin_mvp
tags:
  - obsidian-plugin
  - side-pane
  - chat-ui
  - mvp
status: implemented
created_at: "2026-05-25"
source: codex
---

# Obsidian Plugin MVP

## 목표

Obsidian 안에 Alexandria 사서와 대화하는 최소 side pane을 만든다.
Plugin은 UI bridge이며, 지식 원본/검색/사서 판단은 heterarchy-alexandria backend가 맡는다.

## MVP UX

- Command Palette: `Ask Alexandria Librarian`.
- 오른쪽 side pane에 chat view 열기.
- 현재 active note path 표시.
- 선택 영역이 있으면 context로 포함.
- 질문 입력 후 local Alexandria API 호출.
- 답변 Markdown 렌더링.
- source refs를 Obsidian wikilink로 표시.
- 버튼:
  - `Save chat`
  - `Append to current note`
  - `Create context note`
  - `Create skill draft`

## plugin 설정

```text
Alexandria API URL: http://127.0.0.1:8000
Operator API key: optional, stored in Obsidian plugin settings if needed
Default project: heterarchy-alexandria
Auto-save transcripts: false by default
```

보안상 operator key는 필수 read-only chat에 요구하지 않는 방향을 우선 검토한다.
provider/settings/OAuth 제어에는 operator key가 필요하다.

## plugin 내부 흐름

```text
activate command
  -> open side pane
  -> get active file path
  -> get selection from active Markdown view
  -> POST /obsidian/librarian/ask
  -> render answer
  -> render source links
  -> optional save action
```

## backend에 넘기는 context

- `active_note_path`
- `active_note_frontmatter` 가능하면 client parse 대신 backend parse 우선
- `selection`
- `query`
- `project`
- `preferred_alexandria_types`
- `save_transcript`

## source link 렌더링

Backend는 가능한 한 아래 둘 다 반환한다.

```text
path: Alexandria/Contexts/Decisions/Obsidian Storage.md
wikilink: [[Alexandria/Contexts/Decisions/Obsidian Storage]]
```

Plugin은 `path`가 vault 안에 있는지 검증하고, Obsidian API로 note를 연다.

## Non-goals

- 전체 Alexandria web UI 복구.
- Obsidian에서 모든 provider/OAuth 설정 관리.
- multi-user SaaS chat.
- graph visualization 재구현.

## 완료 기준

- command palette에서 side pane을 열 수 있다.
- 현재 note와 selection을 backend로 보낼 수 있다.
- 답변과 source link를 렌더링한다.
- `Save chat`이 `Alexandria/_Ops/Librarian/Chats` note를 만든다.
- backend unavailable 상태를 사용자에게 명확히 보여준다.
