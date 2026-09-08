# Recall Assets Guide 01 — Markdown/Obsidian first

## 목적

Skill/prompt 자산은 더 이상 heterarchy-alexandria SQLite CRUD로 저장하지 않는다.
기본 보관 위치는 로컬 Markdown 또는 Obsidian vault이며, heterarchy-alexandria는
agent가 필요한 배경 기억을 찾고 MCP note-write boundary로 재사용 자산을 저장한다.

## 조회 순서

1. 현재 세션과 로컬 Hermes skills/prompts를 먼저 확인한다.
2. 로컬 Markdown/Obsidian vault에서 skill/prompt 파일을 검색한다.
3. 필요한 프로젝트 배경, 결정, handoff, research note는 Alexandria Context Vault/Memory Compact에서 recall한다.
4. 그래도 없으면 `alexandria_search` 결과를 근거로 skill/prompt Markdown 자산을 직접 작성한다.

## 저장 원칙

- 재사용 가능한 skill/prompt는 Markdown 파일로 저장한다.
- heterarchy-alexandria backend에는 SQLite skill/prompt CRUD로 등록하지 않는다.
- 저장한 자산은 `alexandria_read_note`로 read-back하고 필요한 경우 `alexandria_reindex_vault`를 실행한다.
