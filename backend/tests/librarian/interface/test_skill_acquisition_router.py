"""Skill acquisition router contract tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.librarian.domain.entities.skill_acquisition_job import SkillAcquisitionJob
from app.librarian.domain.event_enum.collaboration_enums import (
    SkillAcquisitionJobStage,
    SkillAcquisitionJobStatus,
)
from app.main import app
from app.obsidian.domain.entities.obsidian_note import ObsidianNote, ObsidianSearchHit
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from dependency_injector import providers
from fastapi.testclient import TestClient
from tests.shared.provider_overrides import override_library_provider


@contextmanager
def _override_librarian_provider(
    provider_name: str,
    value: object,
) -> Iterator[None]:
    """Temporarily override one librarian container provider."""
    provider = app.state.container.librarian.providers[provider_name]
    with provider.override(providers.Object(value)):
        yield


class FakeSkillAcquisitionService:
    """Deterministic durable acquisition job service for router tests."""

    def __init__(
        self,
        *,
        status: SkillAcquisitionJobStatus = SkillAcquisitionJobStatus.ACCEPTED,
        result_summary: str = "Skill acquisition job accepted.",
    ) -> None:
        """Initialize captured job state."""
        self.status = status
        self.result_summary = result_summary
        self.request_job_calls: list[str] = []
        self.job = SkillAcquisitionJob(
            id="skill-acquisition-1",
            prompt="Need a browser automation skill",
            agent_name="Hermes",
            project="heterarchy-alexandria",
            task_summary="Investigate Playwright usage.",
            status=self.status,
            provider_id="00000000-0000-4000-8000-000000000501",
            librarian_profile_id=None,
            skill_id=None,
            context_id=None,
            result_summary=self.result_summary,
            evidence_urls=[],
            error_message=None,
            created_at=datetime(2026, 5, 18, 17, 30, tzinfo=UTC),
            updated_at=datetime(2026, 5, 18, 17, 30, tzinfo=UTC),
            completed_at=None,
            stage=SkillAcquisitionJobStage.REQUEST_ACCEPTED,
        )

    async def request_job(
        self,
        *,
        prompt: str,
        agent_name: str = "Hermes",
        project: str | None = None,
        task_summary: str | None = None,
        provider_id: str | None = None,
        librarian_profile_id: str | None = None,
        search_snapshot: dict[str, object] | None = None,
        acquisition_override_reason: str | None = None,
    ) -> SkillAcquisitionJob:
        """Return one accepted durable job."""
        self.request_job_calls.append(prompt)
        self.job = SkillAcquisitionJob(
            id="skill-acquisition-1",
            prompt=prompt,
            agent_name=agent_name,
            project=project,
            task_summary=task_summary,
            status=self.status,
            provider_id=provider_id,
            librarian_profile_id=librarian_profile_id,
            skill_id=None,
            context_id=None,
            result_summary=self.result_summary,
            evidence_urls=[],
            error_message=None,
            created_at=datetime(2026, 5, 18, 17, 30, tzinfo=UTC),
            updated_at=datetime(2026, 5, 18, 17, 30, tzinfo=UTC),
            completed_at=None,
            stage=SkillAcquisitionJobStage.REQUEST_ACCEPTED,
            search_snapshot=search_snapshot,
            acquisition_override_reason=acquisition_override_reason,
            prompt_reference="Prompts/Task Prompts/Librarian Operating Prompt v0.1.md",
            prompt_reference_hash="7" * 64,
        )
        return self.job

    async def get_job(self, job_id: str) -> SkillAcquisitionJob:
        """Return the captured job."""
        _ = job_id
        return self.job


class FakeSkillAcquisitionRunner:
    """Minimal non-network background runner for scheduling checks."""

    def __init__(self) -> None:
        """Initialize runner call history."""
        self.run_job_calls: list[str] = []
        self.publisher_passed: list[bool] = []

    async def run_job(self, job_id: str, *, artifact_publisher=None) -> None:  # type: ignore[no-untyped-def]
        """Record one scheduled background run."""
        self.run_job_calls.append(job_id)
        self.publisher_passed.append(artifact_publisher is not None)


def test_skill_acquisition_job_routes_return_sanitized_durable_status() -> None:
    """Skill acquisition routes should create and poll durable sanitized jobs."""
    service = FakeSkillAcquisitionService()
    runner = FakeSkillAcquisitionRunner()

    with (
        override_library_provider("skill_acquisition_service", service),
        _override_librarian_provider("skill_acquisition_runner", runner),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        create_response = client.post(
            "/librarians/skill-acquisition-jobs",
            json={
                "prompt": "Need a browser automation skill",
                "agent_name": "Hermes",
                "project": "heterarchy-alexandria",
                "task_summary": "Investigate Playwright usage.",
                "search_snapshot": {
                    "decision": "NOT_FOUND",
                    "gaps": ["No matching Playwright skill."],
                },
            },
        )
        status_response = client.get(
            "/librarians/skill-acquisition-jobs/skill-acquisition-1"
        )

    assert create_response.status_code == 202
    assert status_response.status_code == 200
    body = create_response.json()
    serialized = f"{body}{status_response.json()}"
    assert body["id"] == "skill-acquisition-1"
    assert body["status"] == "ACCEPTED"
    assert body["result_available"] is False
    assert body["prompt"] == "Need a browser automation skill"
    assert "provider_id" not in body
    assert "librarian_profile_id" not in body
    assert body["search_snapshot"] == {
        "decision": "NOT_FOUND",
        "gaps": ["No matching Playwright skill."],
    }
    assert body["acquisition_override_reason"] is None
    assert body["prompt_reference"].endswith("Librarian Operating Prompt v0.1.md")
    assert body["prompt_reference_hash"] == "7" * 64
    assert "SECRET" not in serialized
    assert "api_key" not in serialized
    assert runner.run_job_calls == ["skill-acquisition-1"]
    assert runner.publisher_passed == [True]


def test_skill_acquisition_job_does_not_schedule_background_runner_for_non_accepted() -> (
    None
):
    """GUIDANCE_ONLY and FAILED jobs should never schedule a background run."""
    for status in (
        SkillAcquisitionJobStatus.GUIDANCE_ONLY,
        SkillAcquisitionJobStatus.FAILED,
    ):
        service = FakeSkillAcquisitionService(
            status=status,
            result_summary="Non-accepted skill-acquisition job.",
        )
        runner = FakeSkillAcquisitionRunner()

        with (
            override_library_provider("skill_acquisition_service", service),
            _override_librarian_provider("skill_acquisition_runner", runner),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            create_response = client.post(
                "/librarians/skill-acquisition-jobs",
                json={
                    "prompt": "Need a browser automation skill",
                    "agent_name": "Hermes",
                    "project": "heterarchy-alexandria",
                    "task_summary": "Investigate Playwright usage.",
                },
            )

        assert create_response.status_code == 202
        assert create_response.json()["status"] == status.value
        assert runner.run_job_calls == []


class FakeObsidianSkillSearchService:
    """Fake Obsidian service for skill-library search route tests."""

    def __init__(self, *, skill_status: str = "active") -> None:
        """Initialize captured search calls."""
        self.search_calls = []
        self.skill_status = skill_status

    async def search(self, query, *, refresh: bool = True):  # type: ignore[no-untyped-def]
        """Return one sufficient active skill hit."""
        self.search_calls.append((query, refresh))
        note = ObsidianNote(
            note_id="skill_browser_automation",
            relative_path="Alexandria/Skills/Drafts/Browser Automation.md",
            alexandria_type=AlexandriaNoteType.SKILL,
            title="Browser Automation",
            status=self.skill_status,
            tags=["browser"],
            project="heterarchy-alexandria",
            source="skill_acquisition",
            content_hash="hash",
            frontmatter={
                "version": "1.0.0",
                "required_tools": ["playwright"],
                "risk_level": "LOW",
                "evidence_urls": ["https://example.com/browser"],
                "requested_status": self.skill_status,
            },
            body=(
                "# Browser Automation\n\n"
                "## Procedure\nUse Playwright with stable selectors.\n"
            ),
            index_status=ObsidianIndexStatus.INDEXED,
            error_message=None,
            size_bytes=100,
            modified_at=datetime(2026, 5, 18, 17, 30, tzinfo=UTC),
            indexed_at=datetime(2026, 5, 18, 17, 30, tzinfo=UTC),
        )
        return [
            ObsidianSearchHit(
                note=note,
                excerpt="Browser automation Playwright stable selectors",
                score=5.0,
            )
        ]


def test_skill_library_search_route_returns_sufficiency_without_creating_job() -> None:
    """Search-first route should query skill notes and avoid acquisition side effects."""
    obsidian_service = FakeObsidianSkillSearchService()
    acquisition_service = FakeSkillAcquisitionService()

    with (
        override_library_provider("obsidian_service", obsidian_service),
        override_library_provider("skill_acquisition_service", acquisition_service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/librarians/skill-library/search",
            json={
                "capability": "Browser Automation",
                "task_goal": "Drive browser checks",
                "project": "heterarchy-alexandria",
                "required_tools": ["playwright"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "FOUND_SUFFICIENT"
    assert body["recommended_action"].startswith("Reuse existing skill")
    assert body["candidates"][0]["id"] == "skill_browser_automation"
    assert body["candidates"][0]["sufficiency_score"] == 10
    assert body["candidates"][0]["hard_gates"]["active_status"]["passed"] is True
    assert body["candidates"][0]["hard_gates"]["required_tools"]["passed"] is True
    assert body["decision_explanation"]["scores"] == [
        {"id": "skill_browser_automation", "sufficiency_score": 10}
    ]
    assert (
        body["decision_explanation"]["hard_gates"]["skill_browser_automation"][
            "active_status"
        ]["passed"]
        is True
    )
    assert body["decision_explanation"]["match_reasons"]["skill_browser_automation"]
    assert body["decision_explanation"]["limitations"] == {
        "skill_browser_automation": []
    }
    assert body["handoff"]["decision"] == "existing_skill_found"
    assert body["handoff"]["skill"]["id"] == "skill_browser_automation"
    assert body["handoff"]["current_task"]["resume_summary"] == "Drive browser checks"
    assert (
        obsidian_service.search_calls[0][0].alexandria_type is AlexandriaNoteType.SKILL
    )
    assert obsidian_service.search_calls[0][1] is True
    assert acquisition_service.request_job_calls == []


def test_skill_library_search_route_returns_existing_draft_handoff_without_job() -> (
    None
):
    """Search-first should rediscover completed draft skills without creating jobs."""
    obsidian_service = FakeObsidianSkillSearchService(skill_status="draft")
    acquisition_service = FakeSkillAcquisitionService()

    with (
        override_library_provider("obsidian_service", obsidian_service),
        override_library_provider("skill_acquisition_service", acquisition_service),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/librarians/skill-library/search",
            json={
                "capability": "Browser Automation",
                "task_goal": "Drive browser checks",
                "project": "heterarchy-alexandria",
                "required_tools": ["playwright"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "FOUND_PARTIAL"
    assert body["candidates"][0]["status"] == "draft"
    assert body["handoff"]["decision"] == "existing_skill_found"
    assert body["handoff"]["skill"]["id"] == "skill_browser_automation"
    assert body["handoff"]["reuse"]["limitations"] == [
        "skill status is draft; human review is required before reuse"
    ]
    assert acquisition_service.request_job_calls == []
