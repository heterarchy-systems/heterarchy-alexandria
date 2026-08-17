---
alexandria_type: job_plan
id: job_obsidian_alexandria_integration_00_index
tags:
  - obsidian
  - heterarchy-alexandria
  - integration-plan
  - index
status: implemented
created_at: "2026-05-25"
source: codex
---

# Obsidian Alexandria Integration — 작업계획 Index

## 목표

heterarchy-alexandria를 **Obsidian/Markdown 원본 저장소**와 연결한다.
SQLite는 원본 저장소가 아니라 검색, 색인, chunk, embedding, job 상태를 위한 보조 캐시로 유지한다.

```text
Obsidian Markdown = canonical knowledge source
SQLite = rebuildable search/index/operation cache
heterarchy-alexandria = backend/CLI/MCP protocol layer
Librarian = optional collaborator and Obsidian chat assistant
```

## 범위

포함한다.

- Obsidian vault layout과 frontmatter 계약 정리.
- vault scan, Markdown parse, SQLite index, search/read API 계획.
- Context, Memory Compact, Skill, Prompt, Librarian Chat write flow 계획.
- 기존 MCP/CLI tool 호환 전략.
- Obsidian 내부 사서 대화창 MVP 계획.
- 보안, 동기화, 테스트, rollout 기준.

포함하지 않는다.

- Next.js/frontend 복구.
- SQLite를 skill/prompt/context의 canonical CRUD 저장소로 되돌리는 작업.
- 외부 공개 SaaS/RBAC 설계.
- Obsidian graph를 primary UX로 강제하는 설계.

## 작업 문서

| 파일 | 작업 |
| --- | --- |
| [01-vault-layout-and-storage-contract.md](01-vault-layout-and-storage-contract.md) | Obsidian vault 구조와 원본 저장 원칙 |
| [02-frontmatter-contract.md](02-frontmatter-contract.md) | Alexandria 관리 Markdown의 YAML frontmatter 계약 |
| [03-sqlite-index-and-retrieval.md](03-sqlite-index-and-retrieval.md) | SQLite 검색/색인/검색결과 원문 로드 계획 |
| [04-agent-mcp-cli-compatibility.md](04-agent-mcp-cli-compatibility.md) | 기존 MCP/CLI tool 호환 매핑 |
| [05-write-and-capture-flows.md](05-write-and-capture-flows.md) | context/compact/skill/prompt/chat Markdown 생성 흐름 |
| [06-librarian-obsidian-chat.md](06-librarian-obsidian-chat.md) | 사서와 Obsidian에서 대화하는 backend 흐름 |
| [07-obsidian-plugin-mvp.md](07-obsidian-plugin-mvp.md) | Obsidian plugin side pane MVP |
| [08-security-sync-and-conflict-rules.md](08-security-sync-and-conflict-rules.md) | local-first 보안, sync, 충돌 규칙 |
| [09-tests-rollout-and-done.md](09-tests-rollout-and-done.md) | 테스트, 단계별 rollout, 완료 기준 |

## 기존 계획과의 관계

이 작업계획은 아래 기존 문서를 대체하기보다 **실행 단위로 재정리**한다.

- `docs/jobs/obsidian-first-librarian-pivot/*`
- `docs/jobs/context-vault-obsidian-storage/*`

기존 문서의 핵심 의도는 유지한다.

- Obsidian/Markdown first.
- SQLite is cache/index, not source of truth.
- Librarian 기능 보존.
- MCP/CLI compatibility 유지.
- frontend 복구 금지.

## 최종 완료 상태

- 모든 Alexandria 관리 지식 자산은 Obsidian Markdown 원본을 가진다.
- 모든 공식 Markdown은 `alexandria_type`과 stable `id`가 있는 frontmatter를 가진다.
- SQLite 삭제 후 reindex하면 검색 기능이 복구된다.
- Hermes/Codex agent는 MCP/CLI로 기존과 비슷한 tool 경험을 유지한다.
- Obsidian 안에서 현재 노트/선택영역을 바탕으로 사서에게 질문할 수 있다.
- 사서 답변은 source wikilink와 함께 표시되고, transcript는 Markdown note로 저장된다.
