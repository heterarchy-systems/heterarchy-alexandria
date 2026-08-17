# MCP Runtime Guide 01 — snippet과 실제 Hermes 등록 구분하기

## 목적

heterarchy-alexandria onboarding 산출물과 Hermes runtime MCP 등록의 차이를 이해한다.

## 두 파일/설정의 역할

### 1. onboarding snippet

```text
~/.hermes/heterarchy-alexandria/mcp-config.json
```

역할:

- heterarchy-alexandria가 생성하는 참고용 MCP server snippet
- 설치 산출물 확인용
- 이것만으로 Hermes runtime tool discovery가 끝나는 것은 아님

### 2. Hermes native MCP config

```text
~/.hermes/config.yaml
```

역할:

- Hermes Agent가 실제로 읽는 runtime MCP 설정
- `mcp_servers.alexandria`가 있어야 `mcp_alexandria_*` tool이 노출됨

## 등록 예

```bash
ALEXANDRIA_CLI="$(command -v heterarchy-alexandria)"
hermes mcp add alexandria   --command "$ALEXANDRIA_CLI"   --args mcp serve   --env ALEXANDRIA_API_URL="http://localhost:8000"   --env ALEXANDRIA_OPERATOR_API_KEY="${ALEXANDRIA_OPERATOR_API_KEY:-}"   --env HERMES_HOME="$HOME/.hermes"
```

## 검증

```bash
hermes mcp list
hermes mcp test alexandria
```

성공 기준:

- `alexandria` server가 enabled/connected 상태
- discovered tools 수가 0보다 큼
- 새 세션에서 `mcp_alexandria_alexandria_search` 같은 tool이 보임

## Gateway/Discord 주의

MCP tool discovery는 Hermes/Gateway 시작 시점에 일어난다. config를 수정한 뒤 현재 Discord 세션에 tool이 안 보이면 대체로 재시작이 필요하다.

```bash
hermes gateway restart
```

또는 연결된 플랫폼에서 제공하는 restart/reset 흐름을 사용한다.
