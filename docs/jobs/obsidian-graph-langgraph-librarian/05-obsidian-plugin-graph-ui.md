---
alexandria_type: job_plan
id: job_obsidian_graph_langgraph_librarian_05_obsidian_plugin_graph_ui
tags:
  - obsidian-plugin
  - graph-ui
  - related-notes
  - librarian
status: implemented
created_at: "2026-05-26"
source: codex
---

# Obsidian Plugin Graph UI

## 목표

현재 Alexandria Librarian side pane을 “질문/답변”에서 “관련 노트 확인 + 그래프 action 승인” UI로 확장한다.

## 현재 상태

Plugin은 이미 다음을 한다.

- right side pane 열기.
- active Markdown note path 읽기.
- selection 읽기.
- `POST /obsidian/librarian/ask` 호출.
- Markdown answer 렌더링.
- source wikilink 표시.
- answer를 현재 note에 append.
- context/skill draft note 생성.

## 추가할 UI

### Related notes panel

```text
Related notes
- START_HERE.md                      cites
- Jobs/Obsidian Integration.md        related
- Skills/Active/Web Research.md       promotes_to
```

기능:

- active note 변경 시 related notes 새로고침.
- source/related 클릭 시 note 열기.
- relation badge 표시.

### Graph actions panel

```text
Proposed graph actions
[ ] Link answer sources to current note
[ ] Add related links to current note
[ ] Create context note from answer
[ ] Create skill draft from answer
[ ] Save transcript

[Apply selected]
```

### OAuth delegate controls

```text
[ ] Ask connected OAuth librarian
Provider: <select>
Profile: <select>
```

### Workflow status

LangGraph workflow가 도입되면 상태를 표시한다.

```text
Status: waiting_for_approval
Thread: librarian_chat_...
```

## Backend calls

```text
GET  /obsidian/notes/by-path/related?path=<active>
POST /obsidian/librarian/ask
POST /obsidian/librarian/workflows
POST /obsidian/librarian/workflows/{thread_id}/resume
POST /obsidian/notes
POST /obsidian/graph/edges
```

## Settings 확장

```json
{
  "apiUrl": "http://127.0.0.1:8000",
  "operatorApiKey": "",
  "defaultProject": "heterarchy-alexandria",
  "autoSaveTranscripts": false,
  "preferredProviderId": "",
  "preferredProfileId": "",
  "showRelatedNotes": true,
  "autoRefreshRelated": true
}
```

## UX 원칙

- 사용자가 승인하지 않은 graph write는 수행하지 않는다.
- source refs는 답변과 함께 보여주되, 현재 note에 쓰는 것은 별도 action이다.
- plugin은 Obsidian native wikilink/openLinkText를 사용한다.
- plugin 자체에 token/secret을 저장하지 않는다.

## 완료 기준

- active note 기준 related notes가 pane에 표시된다.
- 사서 답변 후 proposed actions를 선택 적용할 수 있다.
- OAuth delegate toggle/provider/profile 선택이 가능하다.
- backend unavailable 상태를 명확히 표시한다.
