import logging

import psycopg2

import re
from gspread.exceptions import GSpreadException
from pydantic import BaseModel, ValidationError
from groq import GroqError
from langchain_groq import ChatGroq
from tools.web_search import search_jobs, scrape_email_from_url, PAKISTAN_JOB_DOMAINS

from config.settings import GROQ_MODEL, GROQ_API_KEYS
from prompts.email_prompt import EMAIL_PROMPT, REVISION_PROMPT
from prompts.extraction_prompt import EXTRACTION_PROMPT
from schemas.models import AgentState, EmailDraft, JobListing
from tools.db_tool import (
    applicant_has_applied,
    insert_application,
    insert_job,
    job_exists,
    log_step,
    update_application_status,
    upsert_applicant,
)
from tools.gmail_tool import send_email
from tools.resume_reader import parse_resume
from tools.sheets_tool import log_job_to_sheet

logger = logging.getLogger(__name__)

# One LLM client per API key, used in round-robin when rate limits are hit.
_llm_pool: list[ChatGroq] = [ChatGroq(model=GROQ_MODEL, api_key=key) for key in GROQ_API_KEYS]


def _invoke_with_fallback(prompt: str) -> object:
    """Call invoke() across all LLM keys until one succeeds."""
    last_error: Exception | None = None
    for llm in _llm_pool:
        try:
            return llm.invoke(prompt)
        except GroqError as exc:
            if "rate_limit" in str(exc).lower() or "429" in str(exc):
                last_error = exc
                continue
            raise
    raise last_error or RuntimeError("All Groq API keys exhausted")


def _structured_with_fallback(schema: type, prompt: str) -> object:
    """Call with_structured_output() across all LLM keys until one succeeds."""
    last_error: Exception | None = None
    for llm in _llm_pool:
        try:
            return llm.with_structured_output(schema).invoke(prompt)
        except GroqError as exc:
            if "rate_limit" in str(exc).lower() or "429" in str(exc):
                last_error = exc
                continue
            raise
    raise last_error or RuntimeError("All Groq API keys exhausted")



class _DraftFields(BaseModel):
    subject: str
    body: str


def strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()

PAKISTAN_LOCATION_KEYWORDS = (
    "pakistan", "karachi", "lahore", "islamabad", "rawalpindi",
    "faisalabad", "multan", "peshawar", "quetta", "sialkot",
    "hyderabad", "gujranwala",
)

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _clean_email(raw_email: str | None) -> str | None:
    if raw_email is None:
        return None
    match = EMAIL_PATTERN.search(raw_email)
    return match.group(0) if match else None

def _is_pakistan_location(location: str) -> bool:
    location_lower = location.lower()
    return any(keyword in location_lower for keyword in PAKISTAN_LOCATION_KEYWORDS)


def _extract_job_from_result(raw: dict) -> JobListing:
    """Build a JobListing directly from a Tavily result dict — no LLM tokens used."""
    url: str = raw.get("url", "")
    title: str = raw.get("title", "") or ""
    content: str = raw.get("content", "") or ""
    raw_content: str = raw.get("raw_content", "") or ""
    # Search snippet first (fast), then full page text if needed.
    combined_snippet = f"{title} {content}"
    combined_full = f"{combined_snippet} {raw_content}"

    _IGNORED_EMAIL_DOMAINS = {
        "example.com", "sentry.io", "w3.org", "schema.org",
        "wixpress.com", "sentry-next.wixpress.com", "licdn.com",
    }

    def _first_real_email(text: str) -> str | None:
        for m in EMAIL_PATTERN.finditer(text):
            addr = m.group(0)
            domain = addr.split("@", 1)[1].lower()
            if domain not in _IGNORED_EMAIL_DOMAINS and not domain.startswith("example"):
                return addr
        return None

    contact_email: str | None = _first_real_email(combined_full)

    # Guess location from content.
    location = ""
    for keyword in PAKISTAN_LOCATION_KEYWORDS:
        if keyword in combined_full.lower():
            location = keyword.title()
            break

    # Strip boilerplate from title to get company (text after " at " or " - ").
    company = ""
    for sep in (" at ", " - ", " | "):
        if sep in title:
            parts = title.split(sep, 1)
            title = parts[0].strip()
            company = parts[1].strip()
            break

    return JobListing(
        title=title,
        company=company,
        location=location,
        job_url=url,
        requirements=content[:500],
        seniority="",
        contact_email=contact_email,
    )

def _run_id(state: AgentState) -> str:
    return str(id(state))


def _log(run_id: str, node_name: str, input_summary: str, output_summary: str, status: str) -> None:
    try:
        log_step(run_id, node_name, input_summary, output_summary, status)
    except psycopg2.Error:
        logger.exception("Failed to log agent step")


def _fail(state: AgentState, run_id: str, node_name: str, error: Exception) -> AgentState:
    state.error = str(error)
    _log(run_id, node_name, "node execution", state.error, "failed")
    return state


def intake_node(state: AgentState) -> AgentState:
    """Extract and store the applicant's resume text."""
    run_id = _run_id(state)
    _log(run_id, "intake_node", "resume intake", "started", "running")
    if state.applicant is None:
        return _fail(state, run_id, "intake_node", ValueError("Applicant profile is required"))

    try:
        state.applicant.resume_text = parse_resume(state.applicant.resume_text)
    except (OSError, ValueError) as error:
        return _fail(state, run_id, "intake_node", error)

    try:
        state.applicant_id = upsert_applicant(state.applicant)
    except psycopg2.Error as error:
        return _fail(state, run_id, "intake_node", error)

    _log(run_id, "intake_node", "resume intake", "resume extracted", "completed")
    return state


def research_node(state: AgentState) -> AgentState:
    """Find raw job search results."""
    run_id = _run_id(state)
    _log(run_id, "research_node", state.search_criteria, "started", "running")
    try:
        state.raw_results = search_jobs(state.search_criteria)
    except (OSError, ValueError) as error:
        return _fail(state, run_id, "research_node", error)

    _log(run_id, "research_node", state.search_criteria, "results stored", "completed")
    return state


def extract_node(state: AgentState) -> AgentState:
    """Convert raw search results into job listings."""
    run_id = _run_id(state)
    _log(run_id, "extract_node", "raw results", "started", "running")
    for raw_result in state.raw_results:
        try:
            response = _invoke_with_fallback(EXTRACTION_PROMPT.format(raw_result=raw_result))
        except GroqError as error:
            state.error = str(error)
            _log(run_id, "extract_node", "raw result", "result skipped", "failed")
            continue
        try:
            job = JobListing.model_validate_json(strip_json_fences(response.content))
        except (TypeError, ValidationError, ValueError) as error:
            state.error = str(error)
            _log(run_id, "extract_node", "raw result", "result skipped", "failed")
            continue
        state.found_jobs.append(job)

    status = "failed" if state.error else "completed"
    _log(run_id, "extract_node", "raw results", "jobs extracted", status)
    return state


def store_node(state: AgentState) -> AgentState:
    """Persist newly found jobs and log them to the spreadsheet."""
    run_id = _run_id(state)
    _log(run_id, "store_node", "found jobs", "started", "running")
    for job in state.found_jobs:
        try:
            exists = job_exists(job.job_url)
        except psycopg2.Error as error:
            return _fail(state, run_id, "store_node", error)
        if exists:
            continue

        try:
            state.job_ids[job.job_url] = insert_job(job)
        except psycopg2.Error as error:
            return _fail(state, run_id, "store_node", error)
        state.new_jobs.append(job)

        try:
            log_job_to_sheet(job, "New")
        except (GSpreadException, OSError) as error:
            return _fail(state, run_id, "store_node", error)

    _log(run_id, "store_node", "found jobs", "new jobs stored", "completed")
    return state


def draft_node(state: AgentState) -> AgentState:
    """Create email drafts for newly stored jobs."""
    run_id = _run_id(state)
    _log(run_id, "draft_node", "new jobs", "started", "running")
    if state.applicant is None:
        return _fail(state, run_id, "draft_node", ValueError("Applicant profile is required"))

    for job in state.new_jobs:
        try:
            prompt = EMAIL_PROMPT.format(
                applicant_profile=state.applicant.model_dump_json(),
                job_listing=job.model_dump_json(),
            )
            response = _invoke_with_fallback(prompt)
        except GroqError as error:
            state.error = str(error)
            _log(run_id, "draft_node", job.job_url, "draft skipped", "failed")
            continue
        try:
            state.drafts.append(EmailDraft.model_validate_json(strip_json_fences(response.content)))
        except (TypeError, ValidationError, ValueError) as error:
            state.error = str(error)
            _log(run_id, "draft_node", job.job_url, "draft skipped", "failed")

    status = "failed" if state.error else "completed"
    _log(run_id, "draft_node", "new jobs", "drafts created", status)
    return state


def send_node(state: AgentState) -> AgentState:
    """Send approved drafts and record their application statuses."""
    run_id = _run_id(state)
    _log(run_id, "send_node", "approved drafts", "started", "running")
    if state.applicant_id is None:
        return _fail(state, run_id, "send_node", ValueError("Applicant identifier is required"))

    for draft in state.approved_drafts:
        job_id = state.job_ids.get(draft.job_url)
        if job_id is None:
            return _fail(state, run_id, "send_node", ValueError("Job identifier is required"))
        job = next((job for job in state.found_jobs if job.job_url == draft.job_url), None)
        if job is None or job.contact_email is None:
            return _fail(state, run_id, "send_node", ValueError("Job contact email is required"))
        try:
            application_id = insert_application(job_id, state.applicant_id, draft.body)
        except psycopg2.Error as error:
            return _fail(state, run_id, "send_node", error)

        try:
            sent = send_email(job.contact_email, draft.subject, draft.body)
        except (OSError, ValueError) as error:
            return _fail(state, run_id, "send_node", error)
        try:
            update_application_status(application_id, "sent" if sent else "failed")
        except psycopg2.Error as error:
            return _fail(state, run_id, "send_node", error)
        if not sent:
            state.error = f"Email delivery failed for {draft.job_url}"

    status = "failed" if state.error else "completed"
    _log(run_id, "send_node", "approved drafts", "emails processed", status)
    return state


def fetch_one_job(state: AgentState) -> AgentState:
    """Search for one new job the applicant hasn't seen or applied to yet."""
    state.error = None
    run_id = _run_id(state)

    seen_urls: set[str] = set()
    raw_results: list[dict] = []

    def _add(results: list[dict]) -> None:
        for r in results:
            u = r.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                raw_results.append(r)

    try:
        # Primary: all Pakistani job board domains.
        _add(search_jobs(
            f"{state.search_criteria} jobs in Pakistan hiring",
            max_results=10,
            include_domains=PAKISTAN_JOB_DOMAINS,
        ))
        # Secondary: city-specific query — returns individual job pages, not aggregate pages.
        _add(search_jobs(
            f"{state.search_criteria} Karachi Lahore Islamabad Pakistan hiring apply",
            max_results=10,
            include_domains=PAKISTAN_JOB_DOMAINS,
        ))
        # Tertiary: broad web search targeting company career pages with contact info.
        _add(search_jobs(
            f"{state.search_criteria} Pakistan company apply email 2026",
            max_results=8,
        ))
    except (OSError, ValueError) as error:
        return _fail(state, run_id, "fetch_one_job", error)

    for raw_result in raw_results:
        result_url: str = raw_result.get("url", "")
        from_pk_domain = any(domain in result_url for domain in PAKISTAN_JOB_DOMAINS)

        # Parse directly — no LLM tokens consumed here.
        try:
            job = _extract_job_from_result(raw_result)
        except Exception:
            continue

        # Skip jobs we have already shown or the applicant has applied to.
        if job.job_url in state.shown_job_urls:
            continue

        # Only enforce location filter for results not from known Pakistani job boards.
        if not from_pk_domain and not _is_pakistan_location(job.location):
            continue

        # If no email in the snippet, try scraping the job page directly.
        if job.contact_email is None:
            job.contact_email = scrape_email_from_url(result_url or job.job_url)

        # No email found — skip silently without adding to shown_job_urls so
        # the next search can try again (the page may have changed).
        if job.contact_email is None:
            continue

        if state.applicant_id is not None:
            try:
                already_applied = applicant_has_applied(state.applicant_id, job.job_url)
            except psycopg2.Error:
                already_applied = False
            if already_applied:
                state.shown_job_urls.append(job.job_url)
                continue

        state.current_job = job
        state.current_draft = None
        state.shown_job_urls.append(job.job_url)
        _log(run_id, "fetch_one_job", state.search_criteria, job.job_url, "completed")
        return state

    state.error = "No new matching jobs found for your current search criteria."
    _log(run_id, "fetch_one_job", state.search_criteria, "no new jobs found", "completed")
    return state


def draft_or_revise_email(state: AgentState, feedback: str | None = None) -> AgentState:
    """Draft a fresh email or revise the current draft using the provided feedback."""
    state.error = None
    run_id = _run_id(state)

    if state.current_job is None:
        return _fail(state, run_id, "draft_or_revise_email", ValueError("No current job set"))
    if state.applicant is None:
        return _fail(state, run_id, "draft_or_revise_email", ValueError("Applicant profile required"))

    if feedback is None or state.current_draft is None:
        prompt = EMAIL_PROMPT.format(
            applicant_profile=state.applicant.model_dump_json(),
            job_listing=state.current_job.model_dump_json(),
        )
    else:
        prompt = REVISION_PROMPT.format(
            previous_draft=state.current_draft.body,
            feedback=feedback,
            job_url=state.current_job.job_url,
        )

    try:
        content: _DraftFields = _structured_with_fallback(_DraftFields, prompt)
    except Exception as error:
        return _fail(state, run_id, "draft_or_revise_email", error)

    state.current_draft = EmailDraft(
        job_url=state.current_job.job_url,
        subject=content.subject,
        body=content.body,
    )
    _log(run_id, "draft_or_revise_email", state.current_job.job_url, "draft ready", "completed")
    return state


def send_current_email(state: AgentState) -> AgentState:
    """Send the current draft email with the resume attached and record the result."""
    state.error = None
    run_id = _run_id(state)

    if state.current_job is None or state.current_draft is None:
        return _fail(state, run_id, "send_current_email", ValueError("No current job or draft"))
    if state.applicant_id is None:
        return _fail(state, run_id, "send_current_email", ValueError("Applicant ID required"))
    if state.current_job.contact_email is None:
        return _fail(state, run_id, "send_current_email", ValueError("No contact email for this job"))

    job = state.current_job
    draft = state.current_draft

    try:
        job_id = insert_job(job)
    except psycopg2.Error as error:
        return _fail(state, run_id, "send_current_email", error)

    try:
        application_id = insert_application(job_id, state.applicant_id, draft.body)
    except psycopg2.Error as error:
        return _fail(state, run_id, "send_current_email", error)

    attachment = state.resume_path if state.resume_path else None
    try:
        sent = send_email(job.contact_email, draft.subject, draft.body, attachment_path=attachment)
    except (OSError, ValueError) as error:
        return _fail(state, run_id, "send_current_email", error)

    send_status = "sent" if sent else "failed"
    try:
        update_application_status(application_id, send_status)
    except psycopg2.Error as error:
        return _fail(state, run_id, "send_current_email", error)

    try:
        log_job_to_sheet(job, "Applied")
    except (GSpreadException, OSError):
        logger.exception("Failed to log job to sheet")

    if not sent:
        state.error = f"Email delivery failed for {job.job_url}"

    _log(run_id, "send_current_email", job.job_url, send_status, "completed")
    return state

