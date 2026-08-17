---
alexandria_type: job_plan
id: job_obsidian_alexandria_integration_01_vault_contract
tags:
  - obsidian
  - storage-contract
  - markdown
  - canonical-source
status: implemented
created_at: "2026-05-25"
source: codex
---

# Vault Layout and Storage Contract

## 결정

Obsidian vault의 Markdown 파일을 heterarchy-alexandria 지식 자산의 canonical source로 사용한다.
SQLite row는 검색/색인/운영 보조이며, 원본이 아니다.

## 기본 layout

```text
ObsidianVault/
  Alexandria/
    START_HERE.md

    Memory Compacts/
    Contexts/
      Decisions/
      Handoffs/
      Bug Root Causes/
      Project Context/
      Research/
      Plans/

    Skills/
      Active/
      Drafts/
      Deprecated/

    Prompts/
      System/
      Agent Roles/
      Task Prompts/
      Eval Prompts/

    Librarian/
      Briefs/
      Chats/
      Research Results/
      Skill Acquisition/

    Indexes/
    Archive/
```

## 환경 설정

필수 설정 후보:

```text
SERVICE_OBSIDIAN_VAULT_PATH=/absolute/path/to/ObsidianVault
SERVICE_ALEXANDRIA_OBSIDIAN_ROOT=Alexandria
SERVICE_MEMORY_COMPACT_NOTE_DIR=Alexandria/Memory Compacts
```

원칙:

- 모든 상대 경로는 vault root 안으로만 resolve한다.
- absolute path, `..`, symlink escape는 거부한다.
- folder는 사람의 탐색 UX를 위한 힌트다.
- 기계 분류는 folder가 아니라 frontmatter의 `alexandria_type`과 `id`를 따른다.

## 저장 대상

Obsidian 원본으로 저장한다.

- `context`: decisions, handoffs, project state, bug root cause, research note, plan.
- `memory_compact`: 24시간/세션 단위 요약과 weekly rollup.
- `skill`: 재사용 가능한 작업 능력/절차.
- `prompt`: 재사용 가능한 prompt/template/role instruction.
- `librarian_brief`: 사서에게 전달한 knowledge packet.
- `librarian_chat`: Obsidian 내 사서 대화 transcript.
- `job_plan`: 구현/마이그레이션/운영 계획.

저장하지 않는다.

- raw secret/API key/token/password.
- OAuth access/refresh token 원문.
- 전체 대화 로그 원문.
- 임시 TODO 진행상황만 있는 노이즈.
- 사용자 동의 없는 민감 개인정보.

## 쓰기 정책

MVP 쓰기 정책:

1. 새 note 생성과 append를 우선한다.
2. 기존 본문 rewrite는 최소화한다.
3. frontmatter update는 본문을 byte-for-byte 보존한다.
4. atomic write: temp file 작성 후 rename.
5. optimistic concurrency: 마지막 index hash 또는 modified time을 비교한다.
6. 쓰기 성공 후 해당 note를 즉시 reindex한다.

## 완료 기준

- temp vault fixture에 위 layout을 만들 수 있다.
- vault root 밖 경로 접근이 테스트에서 거부된다.
- frontmatter가 있는 note와 없는 note의 처리 정책이 문서화된다.
- Memory Compact는 기존 `SERVICE_MEMORY_COMPACT_NOTE_DIR` 흐름과 충돌하지 않는다.
