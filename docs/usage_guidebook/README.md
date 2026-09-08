# heterarchy-alexandria Usage Guidebook

이 폴더는 처음 사용하는 사람이 heterarchy-alexandria를 Hermes와 함께 사용하는 방법을 기능별로 익히기 위한 가이드북이다.

## 폴더/파일 규칙

각 기능은 자기 폴더를 가진다.

```text
docs/usage_guidebook/<feature_folder>/<feature>_guide_<number>.md
```

예:

```text
docs/usage_guidebook/hermes_policy/hermes_policy_guide_01.md
docs/usage_guidebook/install_onboard/install_onboard_guide_01.md
```

규칙:

- `<feature_folder>`는 기능 이름을 snake_case로 쓴다.
- `<feature>`는 폴더명과 맞춘다.
- `<number>`는 `01`, `02`처럼 두 자리 번호로 증가시킨다.
- 한 파일은 하나의 실제 사용 시나리오를 다룬다.
- secret/API key/token 값은 예제에 실제 값으로 쓰지 않는다. 필요하면 `<operator-key>` 또는 `[REDACTED]`를 사용한다.

## 현재 가이드

언어별 설치 guidebook은 `docs/install_guides/`로 분리했다.

| 언어 | 설치 가이드 |
| --- | --- |
| 한국어 | [../install_guides/ko/install.md](../install_guides/ko/install.md) |
| English | [../install_guides/en/install.md](../install_guides/en/install.md) |
| 简体中文 | [../install_guides/zh/install.md](../install_guides/zh/install.md) |
| 日本語 | [../install_guides/ja/install.md](../install_guides/ja/install.md) |

| 기능 | 가이드 | 목적 |
| --- | --- | --- |
| install_onboard | [install_onboard_guide_01.md](install_onboard/install_onboard_guide_01.md) | 처음 설치자가 Hermes에 Alexandria를 붙이는 기본 흐름 |
| hermes_policy | [hermes_policy_guide_01.md](hermes_policy/hermes_policy_guide_01.md) | local-first 운영 계약과 Memory Steward 상태 확인 |
| mcp_runtime | [mcp_runtime_guide_01.md](mcp_runtime/mcp_runtime_guide_01.md) | MCP snippet과 Hermes runtime 등록 차이 |
| self_acquisition | [self_acquisition_guide_01.md](self_acquisition/self_acquisition_guide_01.md) | 사서 없이 Hermes가 직접 조사/후보 제출하는 흐름 |
| context_recall | [context_recall_guide_01.md](context_recall/context_recall_guide_01.md) | context 저장 후 recall/Context Pack을 확인하는 첫 기능 smoke test |
| context_rag_benchmark | [context_rag_benchmark_guide_02.md](context_rag_benchmark/context_rag_benchmark_guide_02.md) | PostgreSQL/pgvector·Rust graph compute·MCP v2 환경의 Golden Query 품질과 latency 기준선 |
| memory_compacts | [memory_compacts_guide_01.md](memory_compacts/memory_compacts_guide_01.md) | 장기기억 요약의 24시간 coverage window와 weekly rollup 기준 |
| obsidian_integration | [obsidian_integration_guide_01.md](obsidian_integration/obsidian_integration_guide_01.md) | Obsidian Markdown 원본 저장소, PostgreSQL index/cache, Memory Steward 연계 |
| library_assets | [library_assets_guide_01.md](library_assets/library_assets_guide_01.md) | skills/prompts candidate search와 selected full-load 흐름 |
| operational_sync | [operational_sync_guide_01.md](operational_sync/operational_sync_guide_01.md) | PostgreSQL/Obsidian 재색인, queued embedding reindex, Rust graph projection, readiness READY 복구 절차 |
| security_privacy | [security_privacy_guide_01.md](security_privacy/security_privacy_guide_01.md) | local-first single-operator 보안/프라이버시 모델 |
| troubleshooting | [troubleshooting_guide_01.md](troubleshooting/troubleshooting_guide_01.md) | 증상 기반 설치/recall/MCP/build 문제 해결 |
| oss_onboarding | [oss_onboarding_guide_01.md](oss_onboarding/oss_onboarding_guide_01.md) | 유명 OSS 온보딩 패턴을 반영한 문서 작성 기준 |

## 핵심 운영 모델

```text
local Hermes skill/prompt/context
→ current Memory Compact
→ Context Vault recall/RAG
→ Alexandria MCP search
→ Memory Steward compact/reconciliation
→ immediate agent/MCP save
→ human view/search/archive/delete curation
```

기본 운영은 local-first다. 현재 상태는 Memory Steward readiness로 확인하고,
필요할 때만 CURRENT compact refresh/reconciliation을 실행한다.


## 추천 읽기 순서

### 처음 쓰는 사용자

```text
install_onboard → obsidian_integration → context_recall → memory_compacts → mcp_runtime → hermes_policy
```

### Agent/Hermes 통합 사용자

```text
mcp_runtime → obsidian_integration → library_assets → self_acquisition → security_privacy
```

### 운영자/공개 전 점검

```text
security_privacy → operational_sync → context_rag_benchmark → troubleshooting → oss_onboarding
```
