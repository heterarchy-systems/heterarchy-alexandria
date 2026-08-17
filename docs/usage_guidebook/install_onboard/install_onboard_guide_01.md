# Install/Onboard Guide 01 — 처음 설치 후 Hermes에 Alexandria 붙이기

## 목적

처음 사용하는 사람이 heterarchy-alexandria를 설치한 뒤 Hermes가 로컬/현재 컨텍스트를 먼저 쓰고, 부족할 때 Alexandria를 자연스럽게 사용할 수 있게 만든다.

heterarchy-alexandria는 **로그인 없는 single-operator/local-first** 시스템이다.
기본 온보딩에는 GPT/Codex OAuth나 provider credential이 필요하지 않으며,
`ALEXANDRIA_OPERATOR_API_KEY` 하나만 settings/provider/OAuth/librarian delegation 같은
control-plane 작업을 보호한다.

## 전제

- heterarchy-alexandria backend가 실행 가능하다.
- `heterarchy-alexandria` CLI가 PATH에 있다.
- Hermes Agent가 설치되어 있다.
- operator key가 필요한 기능은 실제 secret을 문서에 남기지 않는다.
- Docker/로컬 기본값은 localhost/private operator 사용을 전제로 한다. 외부 노출 전에는 VPN,
  reverse proxy auth, firewall allowlist, SSH tunnel 중 하나 이상의 access boundary를 둔다.

## 빠른 흐름

```bash
set -a
[ -f .env ] && . ./.env
set +a

export ALEXANDRIA_API_URL="${ALEXANDRIA_API_URL:-http://localhost:8000}"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export ALEXANDRIA_OPERATOR_API_KEY="${ALEXANDRIA_OPERATOR_API_KEY:-}"

heterarchy-alexandria --base-url "$ALEXANDRIA_API_URL" --json health

heterarchy-alexandria --json hermes onboard   --hermes-home "$HERMES_HOME"   --api-url "$ALEXANDRIA_API_URL"   --operator-api-key "${ALEXANDRIA_OPERATOR_API_KEY:-}"   --install-prompts   --install-mcp
```

## 확인

```bash
heterarchy-alexandria --json hermes doctor   --hermes-home "$HERMES_HOME"   --api-url "$ALEXANDRIA_API_URL"   --operator-api-key "${ALEXANDRIA_OPERATOR_API_KEY:-}"

heterarchy-alexandria --json hermes policy status --hermes-home "$HERMES_HOME"
```

성공 기준:

- `skill_installed: true`
- `mcp_config_installed: true`
- `policy_installed: true`
- policy `enabled: true`
- policy `mode: local_first_library_when_needed`

## Runtime 사용 계약

설치 성공은 “OAuth 연결”이나 “MCP discovery”에서 끝나지 않는다. Hermes가 실제 작업에 들어갈 때 아래 계약을 따라야 한다.

1. 현재 대화, Hermes local memory, loaded/local/built-in skill을 먼저 사용한다.
2. 충분하면 Alexandria를 호출하지 않는다.
3. 부족하거나 이전 작업을 이어가거나 durable/shared context가 필요하면 current Memory Compact를 먼저 읽는다.
4. 그래도 빈틈이 있으면 Context Vault recall/RAG로 필요한 결정/핸드오프/버그 원인/compact detail만 좁게 찾는다.
5. START_HERE는 unfamiliar agent가 로컬 맥락이 부족할 때 보는 도서관 입구다.
6. librarian은 optional이며 기본적으로 사용자의 명시 요청이 있을 때만 사용한다. Memory Compact/Context Vault 조회는 사서 위임과 별개다.

## Hermes MCP runtime 등록

`~/.hermes/heterarchy-alexandria/mcp-config.json`은 snippet이다. 실제 Hermes tool discovery는 `~/.hermes/config.yaml`의 `mcp_servers` 등록을 봐야 한다.

```bash
ALEXANDRIA_CLI="$(command -v heterarchy-alexandria)"
hermes mcp add alexandria   --command "$ALEXANDRIA_CLI"   --args mcp serve   --env ALEXANDRIA_API_URL="$ALEXANDRIA_API_URL"   --env ALEXANDRIA_OPERATOR_API_KEY="${ALEXANDRIA_OPERATOR_API_KEY:-}"   --env HERMES_HOME="$HERMES_HOME"

hermes mcp test alexandria
```

설정 후 Hermes CLI/Gateway/Discord 세션을 재시작한다.

## 흔한 오해

- `mcp-config.json`만 있으면 Hermes가 tool을 자동 발견한다고 생각하면 안 된다.
- operator key는 OAuth token이 아니다. protected librarian/settings route에는 operator header가 필요하다.
- 사서가 없어도 설치는 성공할 수 있다. Hermes self-acquisition이 fallback이다.
- Alexandria는 local memory 대체물이 아니다. local-first, Alexandria-when-needed가 기본 계약이다.
- 장기기억 조회는 사서 호출이 아니다. 사서는 사용자가 위임을 요청했거나 별도 정책이 있을 때만 쓴다.

## 선택 사항: 외부 사서 provider / GPT-Codex OAuth

ChatGPT/Codex OAuth와 OpenAI API key provider는 기본 설치가 아니라 선택 사서 위임 기능이다.
Settings → Librarians에서 provider를 연결한 뒤에만 external librarian delegation이 해당 provider를 사용할 수 있다.
OAuth token은 브라우저 상태나 문서에 남기지 않고 backend provider secret store에만 저장한다.
