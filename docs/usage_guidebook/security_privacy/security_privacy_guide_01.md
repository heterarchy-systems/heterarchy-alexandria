# Security & Privacy Guide 01 — local-first single-operator 운영

## 한 줄 요약

heterarchy-alexandria는 로그인/RBAC SaaS가 아니라 **local-first single-operator** 도구다. 외부 공개 전에 반드시 별도 access boundary를 둔다.

## 인증 모델

- 사용자 계정, 세션 로그인, RBAC는 없다.
- 민감 control-plane route는 operator key로 보호한다.
- active Alexandria application secret은 `ALEXANDRIA_OPERATOR_API_KEY` 하나다.
- backend service config 값은 repo root `.env`의 `ALEXANDRIA_OPERATOR_API_KEY`로 주입된다.
- client/CLI/MCP는 `ALEXANDRIA_OPERATOR_API_KEY`를 header로 전달한다.

## 보호되는 기능 예

- provider/settings 변경
- OAuth start/poll/refresh/status
- librarian delegation/job 조회
- 외부 provider credential이 필요한 control-plane 작업

## 네트워크 노출 규칙

기본값은 localhost/private use다.

공개망 또는 팀 네트워크에 노출하기 전 하나 이상을 둔다.

- VPN
- reverse proxy auth
- firewall allowlist
- SSH tunnel
- private subnet / Tailscale 같은 overlay network

## 저장하면 안 되는 것

- raw API key/token/password/credential
- OAuth access token/refresh token 원문
- 전체 대화 로그
- 임시 TODO 진행상황
- 사용자 동의 없는 민감 개인정보

## 저장해도 좋은 것

- decision/handoff/bug-root-cause/plan
- reusable workflow
- memory compact
- source refs가 있는 research/context
- skill/prompt candidate와 evidence URL

## 점검 명령

```bash
heterarchy-alexandria context doctor-rag
heterarchy-heterarchy-alexandria policy status --hermes-home "$HOME/.hermes"
```

operator key 값 자체는 출력하지 않는다. presence, command success, 401 여부로만 확인한다.
