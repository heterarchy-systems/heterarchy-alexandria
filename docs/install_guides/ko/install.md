# heterarchy-alexandria 설치

프론트엔드 런타임은 제거되었습니다. 이제 backend/CLI/MCP 서비스와 Obsidian Markdown vault를 연결합니다.

## 자동 생성 vault로 설치

터미널 1:

```bash
cd backend
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000
```

터미널 2, backend가 켜진 뒤:

```bash
cd backend
curl -fsS -X POST http://127.0.0.1:8000/obsidian/init
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild
```

Obsidian에서 다음 vault를 엽니다.

```text
~/.hermes/heterarchy-alexandria/data/obsidian-vault
```

## 이미 만든 `Alexandria` vault에 붙이기

Obsidian에서 이미 `~/Desktop/Alexandria` vault를 만들었다면 이렇게 설정합니다.

```bash
cd backend
export SERVICE_OBSIDIAN_VAULT_PATH="$HOME/Desktop/Alexandria"
export SERVICE_ALEXANDRIA_OBSIDIAN_ROOT="."
uv sync --locked --no-editable
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`--alexandria-obsidian-root "."`는 vault 자체를 Alexandria 작업공간으로 쓰겠다는 뜻입니다. 그래서 `Alexandria/Alexandria` 중첩 폴더가 생기지 않습니다.

## Backend와 MCP surface 확인

```bash
brew install --cask obsidian
curl -fsS http://127.0.0.1:8000/operations/readiness | jq
curl -fsS -X POST http://127.0.0.1:8000/obsidian/index/rebuild | jq
```

## Docker Compose

```bash
docker compose up --build
```

backend는 `http://127.0.0.1:8000`에서 실행됩니다.
