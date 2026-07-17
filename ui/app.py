import hashlib
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

import streamlit as st

from graph.nodes import draft_or_revise_email, fetch_one_job, send_current_email
from schemas.models import AgentState, ApplicantProfile
from tools.db_tool import (
    load_session_state,
    save_session_state,
    upsert_applicant,
)
from tools.resume_reader import parse_resume


def _thread_id(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()[:16]


def _save(state: AgentState) -> None:
    save_session_state(st.session_state.thread_id, state)


def _go(screen: str) -> None:
    st.session_state.screen = screen
    st.rerun()


st.title("CareerPilot")

if "screen" not in st.session_state:
    st.session_state.screen = "intake"

screen = st.session_state.screen


if screen == "intake":
    resume_file = st.file_uploader("Resume", type=["pdf", "docx"])
    name = st.text_input("Name")
    email = st.text_input("Email")
    target_role = st.text_input("Target role")
    search_criteria = st.text_input("Search criteria")

    if st.button("Start"):
        if not all([resume_file, name, email, target_role, search_criteria]):
            st.error("Complete all fields and upload a resume.")
            st.stop()

        thread_id = _thread_id(email)
        st.session_state.thread_id = thread_id

        # Try to resume an existing session for this email.
        existing = load_session_state(thread_id)
        if existing is not None and existing.current_job is not None:
            # Update resume if user uploaded a new one.
            suffix = Path(resume_file.name).suffix
            resume_dir = Path("resumes") / thread_id
            resume_dir.mkdir(parents=True, exist_ok=True)
            resume_path = resume_dir / Path(resume_file.name).name
            resume_path.write_bytes(resume_file.getbuffer())
            existing.resume_path = str(resume_path)

            # If the cached job has no contact email (pre-filter session), fetch a new one.
            if existing.current_job.contact_email is None:
                existing.current_job = None
                existing.current_draft = None
                existing.error = None
                with st.spinner("Finding a job with contact details..."):
                    existing = fetch_one_job(existing)
                _save(existing)
                st.session_state.state = existing
                _go("no_more_jobs" if existing.error else "job_view")

            _save(existing)
            st.session_state.state = existing
            next_screen = "draft_view" if existing.current_draft is not None else "job_view"
            _go(next_screen)


        # Fresh session: parse resume and upsert applicant.
        resume_dir = Path("resumes") / thread_id
        resume_dir.mkdir(parents=True, exist_ok=True)
        resume_path = resume_dir / Path(resume_file.name).name
        resume_path.write_bytes(resume_file.getbuffer())

        try:
            resume_text = parse_resume(str(resume_path))
        except (OSError, ValueError) as error:
            st.error(str(error))
            st.stop()

        applicant = ApplicantProfile(
            name=name,
            email=email,
            target_role=target_role,
            skills=[],
            resume_text=resume_text,
        )

        try:
            applicant_id = upsert_applicant(applicant)
        except Exception as error:
            st.error(f"Database error: {error}")
            st.stop()

        state = AgentState(
            applicant=applicant,
            applicant_id=applicant_id,
            search_criteria=search_criteria,
            resume_path=str(resume_path),
        )

        with st.spinner("Finding a matching job..."):
            state = fetch_one_job(state)

        _save(state)
        st.session_state.state = state
        _go("no_more_jobs" if state.error else "job_view")


elif screen == "job_view":
    state: AgentState = st.session_state.state
    job = state.current_job

    st.subheader(f"{job.title} at {job.company}")
    st.write(f"**Location:** {job.location}")
    st.write(f"**Seniority:** {job.seniority}")
    st.write(job.requirements)
    if job.job_url:
        st.caption(job.job_url)

    col1, col2 = st.columns(2)

    if col1.button("Write email"):
        with st.spinner("Drafting email..."):
            state = draft_or_revise_email(state)
        _save(state)
        st.session_state.state = state
        if state.error:
            st.error(state.error)
        else:
            _go("draft_view")

    if col2.button("Skip / next job"):
        state.current_job = None
        state.current_draft = None
        state.error = None
        with st.spinner("Finding next job..."):
            state = fetch_one_job(state)
        _save(state)
        st.session_state.state = state
        _go("no_more_jobs" if state.error else "job_view")


elif screen == "draft_view":
    state: AgentState = st.session_state.state
    job = state.current_job
    draft = state.current_draft

    st.subheader(f"{job.title} at {job.company}")
    st.write(f"**Subject:** {draft.subject}")
    st.markdown("---")
    st.text_area("Email preview", value=draft.body, height=350, disabled=True, label_visibility="collapsed")
    st.markdown("---")

    feedback = st.text_input("Feedback (leave blank to send as-is)")

    col1, col2 = st.columns(2)

    if col1.button("Send as-is"):
        with st.spinner("Sending email..."):
            st.write("DEBUG resume_path:", state.resume_path)
            st.write("DEBUG file exists:", Path(state.resume_path).exists() if state.resume_path else "no path set")
            state = send_current_email(state)
        _save(state)
        st.session_state.state = state
        _go("result")

    if col2.button("Revise with feedback"):
        if not feedback.strip():
            st.warning("Enter feedback before clicking revise.")
        else:
            with st.spinner("Revising draft..."):
                state = draft_or_revise_email(state, feedback=feedback.strip())
            _save(state)
            st.session_state.state = state
            if state.error:
                st.error(state.error)
            else:
                st.rerun()


elif screen == "result":
    state: AgentState = st.session_state.state
    job = state.current_job

    if state.error:
        st.error(f"Send failed: {state.error}")
    else:
        st.success(f"Email sent for {job.title} at {job.company}.")

    if st.button("Next job"):
        state.current_job = None
        state.current_draft = None
        state.error = None
        with st.spinner("Finding next job..."):
            state = fetch_one_job(state)
        _save(state)
        st.session_state.state = state
        _go("no_more_jobs" if state.error else "job_view")


elif screen == "no_more_jobs":
    state: AgentState = st.session_state.state
    st.info("No new matching jobs found for your current search criteria.")

    new_criteria = st.text_input("Try different search criteria", value=state.search_criteria)

    if st.button("Search again"):
        if not new_criteria.strip():
            st.warning("Enter search criteria.")
        else:
            state.shown_job_urls = []
            state.search_criteria = new_criteria.strip()
            state.error = None
            with st.spinner("Searching..."):
                state = fetch_one_job(state)
            _save(state)
            st.session_state.state = state
            _go("no_more_jobs" if state.error else "job_view")
