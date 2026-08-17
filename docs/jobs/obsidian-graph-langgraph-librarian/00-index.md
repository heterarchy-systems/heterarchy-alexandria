---
alexandria_type: job_plan
id: job_obsidian_graph_langgraph_librarian_00_index
tags:
  - obsidian
  - graph
  - langgraph
  - librarian
  - index
status: implemented
created_at: "2026-05-26"
source: codex
---

# Obsidian Graph + LangGraph Librarian — 작업계획 Index

## 목표

heterarchy-alexandria를 단순 Obsidian 검색/사서 답변에서 한 단계 확장한다.
Obsidian은 계속 **장기기억 원본**이고, SQLite는 **검색/관계 index**, LangGraph는 **사서 작업 흐름 상태머신**으로 사용한다.

```text
Obsidian Markdown = canonical long-term knowledge
Obsidian Graph = human-facing link/backlink view
SQLite = rebuildable search/index/edge cache
LangGraph = librarian workflow/checkpoint/human-in-the-loop engine
OAuth provider = optional external librarian delegate
heterarchy-alexandria = backend/CLI/MCP/plugin bridge
```

## 핵심 결정

- LangGraph를 장기기억 저장소로 쓰지 않는다.
- LangGraph checkpoint는 실행 상태, pause/resume, 승인 대기, tool 결과 기록에만 쓴다.
- 모든 영구 지식은 Obsidian Markdown frontmatter/body로 남긴다.
- Graph UX는 Obsidian 기본 graph가 읽을 수 있는 wikilink/backlink를 생성하는 방식으로 구현한다.
- OAuth token/refresh token은 Obsidian에 저장하지 않고 backend provider secret store에만 저장한다.

## 범위

포함한다.

- Graph relation frontmatter 계약 정의.
- `obsidian_edges` SQLite cache/index 계획.
- 사서 답변/저장 흐름에서 wikilink와 relation 자동 생성.
- LangGraph 기반 사서 workflow MVP.
- OAuth provider 위임 node 설계.
- Obsidian plugin side pane에 Related notes / Graph actions UI 추가.
- setup/daemon/install 안정화.
- 테스트, rollout, 완료 기준.

포함하지 않는다.

- Next.js/frontend 복구.
- LangGraph Platform/SaaS 의존.
- Obsidian graph 자체를 재구현하는 별도 canvas/visualization.
- OAuth token을 Obsidian plugin 설정에 저장.
- SQLite를 canonical memory store로 되돌리는 작업.

## 작업 문서

| 파일 | 작업 |
| --- | --- |
| [01-graph-relation-contract.md](01-graph-relation-contract.md) | Obsidian graph relation/frontmatter/wikilink 계약 |
| [02-sqlite-edge-index-and-retrieval.md](02-sqlite-edge-index-and-retrieval.md) | `obsidian_edges` cache와 related-note retrieval 계획 |
| [03-langgraph-librarian-workflow.md](03-langgraph-librarian-workflow.md) | LangGraph 사서 workflow MVP 설계 |
| [04-oauth-delegation-and-provider-routing.md](04-oauth-delegation-and-provider-routing.md) | OAuth provider 위임과 보안 경계 |
| [05-obsidian-plugin-graph-ui.md](05-obsidian-plugin-graph-ui.md) | Obsidian plugin UI 확장 |
| [06-setup-daemon-and-install-hardening.md](06-setup-daemon-and-install-hardening.md) | setup/install/daemon/migration 자동화 안정화 |
| [07-tests-rollout-and-done.md](07-tests-rollout-and-done.md) | 테스트, rollout, 완료 기준 |

## 우선순위

1. install/daemon/migration 안정화.
2. Graph relation 계약과 edge index.
3. 사서 답변 저장 시 source/related wikilink 자동 생성.
4. plugin Related notes UI.
5. LangGraph local workflow MVP.
6. OAuth delegated librarian node.
7. human approval 후 note 저장/reindex 자동화.

## 최종 완료 상태

- Obsidian Graph에서 Alexandria note 간 source/derived/related 관계가 보인다.
- 사서 답변에는 source wikilink와 action preview가 있다.
- 사서가 만든 Context/Skill/Prompt/Memory Compact는 원본 source와 backlink를 가진다.
- 사용자가 승인하기 전에는 외부 OAuth 사서 결과가 영구 저장되지 않는다.
- backend 재시작 후에도 진행 중인 LangGraph workflow를 재개할 수 있다.
- SQLite edge cache를 삭제해도 Obsidian Markdown에서 재생성할 수 있다.
