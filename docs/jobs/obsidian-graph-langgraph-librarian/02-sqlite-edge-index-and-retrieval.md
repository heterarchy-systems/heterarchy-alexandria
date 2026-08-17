---
alexandria_type: job_plan
id: job_obsidian_graph_langgraph_librarian_02_sqlite_edge_index_retrieval
tags:
  - sqlite
  - graph
  - index
  - retrieval
status: implemented
created_at: "2026-05-26"
source: codex
---

# SQLite Edge Index and Retrieval

## 목표

Obsidian Markdown에서 relation을 읽어 `obsidian_edges` cache를 만들고, 현재 note 기준 related notes를 빠르게 찾는다.

## 원칙

- SQLite는 edge 원본이 아니다.
- edge는 frontmatter와 wikilink에서 재생성 가능해야 한다.
- 검색 결과는 DB row id보다 Obsidian `id`, `path`, `wikilink`를 우선 반환한다.

## 테이블 후보

```text
obsidian_edges
- edge_id TEXT primary key
- source_note_id TEXT not null
- source_path TEXT not null
- target_note_id TEXT null
- target_path TEXT not null
- relation TEXT not null
- confidence REAL not null default 1.0
- source_kind TEXT not null  # frontmatter | wikilink | inferred | user_approved
- created_at TEXT not null
- indexed_at TEXT not null
```

인덱스:

```text
idx_obsidian_edges_source_note_id
idx_obsidian_edges_target_note_id
idx_obsidian_edges_relation
idx_obsidian_edges_target_path
```

## Edge 생성 입력

1. frontmatter relation:
   - `source_refs`
   - `derived_from`
   - `related`
   - `supersedes`
   - `promotes_to`
   - `blocks`
   - `resolves`
2. body wikilink:
   - `[[path]]`
   - `[[path|label]]`
3. 사서 action preview:
   - 아직 승인 전이면 `inferred`로만 응답하고 저장하지 않는다.
4. 사용자 승인 action:
   - 승인 후 `user_approved` edge로 frontmatter/body에 저장한다.

## Retrieval API 후보

Backend HTTP:

```text
GET  /obsidian/notes/{id}/related
GET  /obsidian/notes/by-path/related?path=<path>
POST /obsidian/graph/edges/rebuild
POST /obsidian/graph/edges
```

CLI:

```bash
heterarchy-alexandria obsidian related --path "START_HERE.md"
heterarchy-alexandria obsidian graph rebuild
```

MCP:

```text
alexandria_get_related_notes
alexandria_rebuild_obsidian_graph_edges
alexandria_save_obsidian_edge
```

## Scoring

Related note ranking:

```text
score = relation_weight + fts_score + recency_boost + same_project_boost
```

relation weight 예시:

| relation | weight |
| --- | ---: |
| `derived_from` | 1.0 |
| `cites` | 0.9 |
| `supersedes` | 0.8 |
| `promotes_to` | 0.8 |
| `related` | 0.6 |
| `wikilink` | 0.5 |
| `inferred` | 0.3 |

## Reindex 흐름

```text
scan markdown
→ parse frontmatter
→ parse body wikilinks
→ upsert obsidian_files
→ delete old edges for note
→ insert current edges
→ mark stale edges for missing notes
```

## 완료 기준

- vault reindex가 `obsidian_edges`를 재생성한다.
- 현재 note 기준 related notes API가 동작한다.
- body wikilink만 있는 일반 Obsidian note도 weak edge로 인식된다.
- SQLite DB 삭제 후 reindex하면 edge cache가 복구된다.
