---
alexandria_type: job_plan
id: job_obsidian_alexandria_integration_08_security_sync_conflict_rules
tags:
  - security
  - sync
  - conflict
  - local-first
status: implemented
created_at: "2026-05-25"
source: codex
---

# Security, Sync, and Conflict Rules

## 보안 모델

heterarchy-alexandria는 local-first single-operator 도구다.
Obsidian integration도 기본적으로 localhost/private 환경을 전제로 한다.

## 저장 금지

Markdown과 SQLite 양쪽 모두에 저장 금지:

- raw API key/token/password.
- OAuth access token/refresh token 원문.
- private key 원문.
- 전체 대화 로그 원문.
- 사용자 동의 없는 민감 개인정보.

## 저장 가능

- decision, handoff, bug root cause.
- project context, research summary.
- Memory Compact.
- reusable skill/prompt candidate.
- source refs/evidence URL.
- 사서 대화 transcript 중 사용자가 저장한 내용.

## secret guardrail

쓰기 전 검사:

```text
candidate markdown
  -> secret pattern scan
  -> high-risk match면 reject 또는 redaction confirmation 필요
  -> redacted body write
  -> warning metadata 기록
```

자동 저장 기본값:

- Memory Compact: agent/API 정책에 따름.
- Librarian Chat transcript: 기본 false, 사용자가 Save Chat 클릭.
- Skill/prompt candidate: DRAFT로 저장.

## sync 충돌 규칙

Obsidian Sync/Git/iCloud 등 외부 sync를 고려한다.

- write 전 last indexed hash 또는 modified time 확인.
- 변경 감지 시 overwrite 금지.
- conflict note 생성 또는 사용자에게 merge 필요 상태 반환.
- frontmatter update는 body 보존.
- id collision은 자동 merge하지 않는다.

## archive/delete

- 기본 archive는 `status: archived` 또는 Archive 폴더 이동이다.
- hard delete는 명시적 API/CLI action에서만 허용한다.
- MCP tool 설명에는 hard delete 위험을 명확히 둔다.

## network exposure

localhost 외부에 노출할 경우 최소 하나를 요구한다.

- VPN/Tailscale.
- reverse proxy auth.
- firewall allowlist.
- SSH tunnel.
- private subnet.

## 완료 기준

- path traversal 테스트가 있다.
- secret redaction/block 테스트가 있다.
- stale hash write conflict 테스트가 있다.
- archive와 hard delete 동작이 분리된다.
- operator key가 필요한 route가 문서화된다.
