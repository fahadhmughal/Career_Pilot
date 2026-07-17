import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/careerpilot")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
os.environ.setdefault("SHEET_ID", "test-sheet-id")
os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account.json")
os.environ.setdefault("GMAIL_CREDENTIALS_FILE", "gmail-credentials.json")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

from graph import nodes
from graph.edges import (
    should_continue_after_extract,
    should_continue_after_research,
)
from schemas.models import AgentState, ApplicantProfile, EmailDraft, JobListing


def test_normal_run_with_search_results(monkeypatch: pytest.MonkeyPatch) -> None:
    applicant = ApplicantProfile(
        name="Ava Khan",
        email="ava@example.com",
        target_role="Python Developer",
        skills=["Python", "PostgreSQL"],
        resume_text="Extracted resume text",
    )
    state = AgentState(applicant=applicant, search_criteria="Python developer jobs")
    job_json = (
        '{"title":"Backend Developer","company":"Acme","location":"Remote",'
        '"job_url":"https://example.com/jobs/1","requirements":"Python",'
        '"seniority":"Mid","contact_email":"jobs@example.com"}'
    )
    draft_json = (
        '{"job_url":"https://example.com/jobs/1","subject":"Backend Developer",'
        '"body":"My Python and PostgreSQL experience matches this role."}'
    )
    mock_llm = Mock()
    mock_llm.invoke.side_effect = [
        SimpleNamespace(content=job_json),
        SimpleNamespace(content=draft_json),
    ]

    monkeypatch.setattr(nodes, "search_jobs", Mock(return_value=[{"url": "https://example.com/jobs/1"}]))
    monkeypatch.setattr(nodes, "llm", mock_llm)
    monkeypatch.setattr(nodes, "job_exists", Mock(return_value=False))
    monkeypatch.setattr(nodes, "insert_job", Mock(return_value=1))
    monkeypatch.setattr(nodes, "log_job_to_sheet", Mock())
    monkeypatch.setattr(nodes, "log_step", Mock())

    nodes.research_node(state)
    nodes.extract_node(state)
    nodes.store_node(state)
    nodes.draft_node(state)

    assert should_continue_after_research(state) == "extract"
    assert should_continue_after_extract(state) == "store"
    assert len(state.found_jobs) == 1
    assert len(state.drafts) == 1
    assert state.error is None


def test_zero_tavily_results_end_with_error(monkeypatch: pytest.MonkeyPatch) -> None:
    state = AgentState(search_criteria="rare role")
    monkeypatch.setattr(nodes, "search_jobs", Mock(return_value=[]))
    monkeypatch.setattr(nodes, "log_step", Mock())

    nodes.research_node(state)

    assert should_continue_after_research(state) == "end"
    assert state.error == "No jobs found. Broaden your search criteria and try again."


def test_malformed_extraction_skips_only_invalid_result(monkeypatch: pytest.MonkeyPatch) -> None:
    state = AgentState(raw_results=[{"url": "https://example.com/invalid"}, {"url": "https://example.com/valid"}])
    valid_job = (
        '{"title":"Data Engineer","company":"Acme","location":"Remote",'
        '"job_url":"https://example.com/valid","requirements":"Python",'
        '"seniority":"Mid","contact_email":null}'
    )
    mock_llm = Mock()
    mock_llm.invoke.side_effect = [
        SimpleNamespace(content="not valid json"),
        SimpleNamespace(content=valid_job),
    ]
    mock_log_step = Mock()

    monkeypatch.setattr(nodes, "llm", mock_llm)
    monkeypatch.setattr(nodes, "log_step", mock_log_step)

    nodes.extract_node(state)

    assert [job.job_url for job in state.found_jobs] == ["https://example.com/valid"]
    assert state.error is not None
    assert any(call.args[-1] == "failed" for call in mock_log_step.call_args_list)


def test_gmail_failure_marks_application_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    applicant = ApplicantProfile(
        name="Ava Khan",
        email="ava@example.com",
        target_role="Python Developer",
        skills=["Python"],
        resume_text="Extracted resume text",
    )
    job = JobListing(
        title="Backend Developer",
        company="Acme",
        location="Remote",
        job_url="https://example.com/jobs/1",
        requirements="Python",
        seniority="Mid",
        contact_email="jobs@example.com",
    )
    draft = EmailDraft(
        job_url=job.job_url,
        subject="Backend Developer",
        body="I am interested in this role.",
    )
    state = AgentState(
        applicant=applicant,
        applicant_id=1,
        found_jobs=[job],
        job_ids={job.job_url: 2},
        approved_drafts=[draft],
    )
    mock_update_status = Mock()

    monkeypatch.setattr(nodes, "insert_application", Mock(return_value=3))
    monkeypatch.setattr(nodes, "send_email", Mock(return_value=False))
    monkeypatch.setattr(nodes, "update_application_status", mock_update_status)
    monkeypatch.setattr(nodes, "log_step", Mock())

    nodes.send_node(state)

    mock_update_status.assert_called_once_with(3, "failed")
    assert state.error == "Email delivery failed for https://example.com/jobs/1"
