# Overview

## 저장소 성격

heterarchy-alexandria는 단순 API Adapter가 아니다.

다음 책임을 가진 Backend다.

- FastAPI와 MCP Boundary
- Pydantic Validation Contract
- SQLAlchemy Persistence
- Obsidian Markdown Canonical Storage
- PostgreSQL FTS, pgvector, Embedding Index
- Neo4j Graph Projection
- Redis Queue / Cache / Coordination
- Context와 Memory Lifecycle
- Librarian 실행
- Skill과 Knowledge Graph 관리

따라서 모든 객체를 하나의 모델 시스템으로 통일하지 않는다. 역할에 따라 Pydantic, Dataclass, TypedDict, SQLAlchemy를 구분한다.

## 개발 철학

- Contract는 명시적으로 만든다.
- Raw 입력은 경계에서 멈춘다.
- 내부 계층은 검증된 값만 전달한다.
- 타입 오류는 실제 결함으로 취급한다.
- 새로운 추상화보다 현재 작업의 안정성을 우선한다.
- 문서나 코드가 존재한다는 이유만으로 완료를 주장하지 않는다.
