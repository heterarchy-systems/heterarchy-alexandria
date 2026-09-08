# OSS Onboarding Guide 01 — README와 기능 가이드 작성 기준

## 목적

heterarchy-alexandria 문서를 유명 OSS 프로젝트의 온보딩 패턴에 맞춰 유지한다.

참고한 패턴:

- FastAPI: 설치 → 최소 예제 → 실행 → interactive docs 확인
- Supabase: local dev / self-host / deployment 경로 분리
- Dify: quick start / features / self-host / security / contributing
- Open WebUI: Docker-first quickstart, troubleshooting, update guide
- LangChain/LangGraph: concepts와 how-to guide 분리
- mem0/Zep: memory add/search/retrieve의 짧은 aha loop 제공
- Backend/CLI/MCP: README는 짧고, 상세는 docs로 위임

## heterarchy-alexandria 문서 원칙

1. README는 판매문서 + 5분 quickstart 역할을 한다.
2. 설치 문서는 성공 상태를 health가 아니라 `capture → recall → inspect`로 정의한다.
3. 기능 가이드는 내부 모듈명이 아니라 user job 기준으로 쓴다.
4. concepts / guides / troubleshooting / security를 분리한다.
5. secret, token, provider credential 예제는 실제 값 없이 placeholder만 쓴다.
6. local-first/single-operator 경계와 네트워크 노출 주의는 반복해서 보인다.

## 기능 가이드 템플릿

```md
# <Feature> Guide NN — <job-to-be-done>

## 목적

## 전제

## 빠른 성공 경로

## 명령/API/MCP 예

## 성공 기준

## 흔한 실패

## 관련 가이드
```

## 현재 guidebook 구조

```text
docs/usage_guidebook/
  install_onboard/
  hermes_policy/
  mcp_runtime/
  context_recall/
  memory_compacts/
  library_assets/
  self_acquisition/
  security_privacy/
  troubleshooting/
  oss_onboarding/
```

## 다음에 추가하면 좋은 가이드

- Docker Compose 운영/업그레이드
- backup/restore
- API reference examples
- MCP client examples
- Memory Compact curation workflow
- RAG relevance tuning
- provider/OAuth setup deep dive
