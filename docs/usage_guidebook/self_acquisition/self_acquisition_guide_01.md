# Self-Acquisition Guide 01 — Hermes가 직접 reusable asset 만들기

## 목적

Hermes가 외부 위임 없이 heterarchy-alexandria를 활용해 reusable asset 후보를 만들 수 있게 한다.

## 기본 흐름

```text
local Hermes skill 확인
→ Alexandria search/recall
→ 관련 asset 없음
→ Hermes가 직접 docs/web/source 조사
→ skill/prompt/context Markdown candidate 작성
→ Alexandria MCP note-write boundary로 저장
→ read-back과 evidence refs 확인
```

## 테스트 프롬프트 예

```text
이제 사서 없이 heterarchy-alexandria self-acquisition 테스트를 진행하세요.

주제:
pytest fixture cleanup strategy

절차:
1. local skill이 없다고 가정하세요.
2. Alexandria RAG 상태를 확인하세요.
3. Alexandria에서 관련 skill/prompt/context를 검색하세요.
4. 적절한 항목이 없으면 직접 reusable skill candidate를 작성하세요.
5. evidence_urls 최소 1개와 source_summary를 포함하세요.
6. job id, result status, evidence, resume context id를 알려주세요.
7. 외부 provider나 등록되지 않은 acquisition job은 호출하지 마세요.
```

## MCP tool 예

도구 이름은 Hermes runtime에서 `mcp_alexandria_*` 형태로 보일 수 있다.

```text
mcp_alexandria_alexandria_rag_status
mcp_alexandria_alexandria_search
alexandria_create_note / alexandria_upsert_note
```

## 후보에 포함할 내용

- reusable title
- when-to-use 조건
- exact steps
- evidence URLs
- source summary
- secret redaction note
- expected harness state

## 금지

- raw secret/API key/token 저장
- 전체 대화 로그 저장
- 단순 TODO 진행상황 저장
- evidence 없는 후보 제출

## 최종 보고 예

```text
- RAG status: FTS healthy, vector disabled
- 검색 결과: 직접 맞는 skill 없음
- note write: 수행함
- note id/path: <note-id-or-path>
- read-back: <verified>
- evidence URLs: <url 목록>
- 확인 위치: Obsidian Markdown note
```
