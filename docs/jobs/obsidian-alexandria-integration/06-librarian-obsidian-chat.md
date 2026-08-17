---
alexandria_type: job_plan
id: job_obsidian_alexandria_integration_06_librarian_obsidian_chat
tags:
  - librarian
  - obsidian-chat
  - backend
  - knowledge-packet
status: implemented
created_at: "2026-05-25"
source: codex
---

# Librarian Obsidian Chat Backend Plan

## 목표

Obsidian 안에서 현재 note/선택영역을 바탕으로 Alexandria 사서에게 질문할 수 있게 한다.
사서는 Obsidian vault index, current Memory Compact, Context Vault recall, skill/prompt notes를 바탕으로 답한다.

## 사용자 흐름

```text
Obsidian side pane
  -> user asks question
  -> plugin sends active note path + selection + query
  -> heterarchy-alexandria builds knowledge packet
  -> self-answer or delegate-to-librarian provider
  -> answer with source refs
  -> plugin renders answer and wikilinks
  -> optional transcript save
```

## Backend endpoint 후보

```text
POST /obsidian/librarian/ask
POST /obsidian/librarian/chats
GET  /obsidian/librarian/chats/{conversation_id}
```

기존 `/librarians/ask`, `/librarians/brief-preview`, skill-acquisition job service를 재사용한다.
새 endpoint는 Obsidian context payload를 받는 thin adapter로 둔다.

## request payload

```json
{
  "query": "이 노트에서 skill 후보를 뽑아줘",
  "active_note_path": "Alexandria/Contexts/Decisions/Obsidian Storage.md",
  "selection": "SQLite는 검색/색인 보조로만 사용한다.",
  "project": "heterarchy-alexandria",
  "preferred_alexandria_types": ["context", "skill", "prompt", "memory_compact"],
  "save_transcript": false,
  "delegate_to_librarian": false
}
```

## response payload

```json
{
  "answer_markdown": "...",
  "source_refs": [
    {
      "id": "ctx_obsidian_storage",
      "path": "Alexandria/Contexts/Decisions/Obsidian Storage.md",
      "wikilink": "[[Alexandria/Contexts/Decisions/Obsidian Storage]]",
      "title": "Obsidian Storage"
    }
  ],
  "action_preview": [
    "create_skill_candidate",
    "save_as_context",
    "append_to_current_note"
  ],
  "conversation_id": "chat_20260525_001",
  "transcript_path": null
}
```

## knowledge packet 구성

우선순위:

1. 현재 note frontmatter/body.
2. 선택 영역.
3. current Memory Compact.
4. query에 맞는 context recall.
5. 관련 skill/prompt search.
6. optional librarian profile/provider info.

예산:

- default input budget은 작게 시작한다.
- source refs는 path/id/title 중심으로 유지한다.
- 전체 note body를 무조건 넣지 않는다.

## transcript note

```md
---
alexandria_type: librarian_chat
id: librarian_chat_20260525_001
tags:
  - librarian
  - obsidian-chat
status: active
created_at: "2026-05-25"
source: obsidian-plugin
conversation_id: chat_20260525_001
project: heterarchy-alexandria
active_note_path: "Alexandria/Contexts/Decisions/Obsidian Storage.md"
linked_note_ids:
  - ctx_obsidian_storage
---

# Librarian Chat — 2026-05-25

## User

## Librarian

## Sources
```

## 완료 기준

- active note와 selection이 포함된 ask 요청을 처리한다.
- 답변에 source refs와 Obsidian wikilink가 포함된다.
- transcript 저장 시 `librarian_chat` frontmatter가 생긴다.
- delegate provider가 없어도 self-answer fallback이 작동한다.
- operator key가 필요한 route와 필요 없는 local read route가 구분된다.
