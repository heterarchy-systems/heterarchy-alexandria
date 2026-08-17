---
alexandria_type: job_plan
id: job_obsidian_graph_langgraph_librarian_06_setup_daemon_install_hardening
tags:
  - setup
  - install
  - daemon
  - migration
  - smoke-test
status: implemented
created_at: "2026-05-26"
source: codex
---

# Setup, Daemon, and Install Hardening

## 목표

현재 수동으로 한 설치 절차를 제품 명령으로 안정화한다.

## 발견된 실전 문제

이번 설치에서 확인한 문제:

- `setup --apply`는 `.env`와 vault 경로를 만들지만 DB migration은 자동 실행하지 않았다.
- migration 전 `/obsidian/init` 호출 시 `obsidian_files` table missing 500이 발생했다.
- generated launchd plist는 `heterarchy-alexandria` command를 직접 호출하지만, local uv 환경에서는 repo working directory가 필요했다.
- plugin symlink에 `data.json`을 쓰면 repo working tree가 더러워질 수 있다.

## 개선 방향

### 1. setup apply 후 migration option

```bash
heterarchy-alexandria setup \
  --mode backend-daemon \
  --apply \
  --write-guidebook \
  --run-migrations
```

또는 기본값으로 local SQLite migration을 실행한다.

### 2. install command 통합

새 command 후보:

```bash
heterarchy-alexandria obsidian install-local \
  --vault-path "$HOME/Desktop/Alexandria" \
  --root "." \
  --install-plugin \
  --install-daemon \
  --run-smoke-test
```

실행 단계:

```text
uv sync/package 확인
setup --apply
alembic upgrade head
plugin copy/symlink
community-plugins.json 업데이트
launchd plist 생성
launchctl bootstrap/kickstart
health check
obsidian init
obsidian reindex
ask smoke test
```

### 3. daemon plist 안정화

launchd plist는 repo-local backend에서 실행되도록 한다.

```text
ProgramArguments:
/bin/zsh -lc "cd <repo>/backend && exec uv run heterarchy-alexandria serve --env-file <env> --host 127.0.0.1 --port 8000"
```

장기적으로는 설치된 wheel/venv entrypoint 경로를 명시하는 방식도 검토한다.

### 4. plugin data 저장 정책

Symlink install인 경우 Obsidian이 plugin `data.json`을 repo plugin directory에 쓸 수 있다.
이를 피하려면 기본은 copy install로 두고, dev mode만 symlink한다.

```text
--plugin-install-mode copy | symlink
```

기본값: `copy`.
개발자 편의: `symlink`.

## Validation output

install-local은 마지막에 아래를 출력한다.

```json
{
  "backend_health": "ok",
  "vault_path": "/Users/.../Desktop/Alexandria",
  "alexandria_root": ".",
  "plugin_enabled": true,
  "indexed_notes": 5,
  "ask_smoke_test": "ok"
}
```

## 완료 기준

- fresh local state에서 한 명령으로 backend/vault/plugin/daemon 설치가 끝난다.
- DB migration 누락으로 500이 발생하지 않는다.
- Obsidian plugin이 repo working tree를 더럽히지 않는다.
- install 후 `health`, `obsidian status`, `ask` smoke test가 통과한다.
