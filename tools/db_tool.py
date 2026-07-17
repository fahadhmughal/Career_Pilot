from collections.abc import Iterator
from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import connection

from config.settings import DATABASE_URL
from schemas.models import AgentState, ApplicantProfile, JobListing


@contextmanager
def get_connection() -> Iterator[connection]:
    """Open a database connection for one operation."""
    database_connection = psycopg2.connect(DATABASE_URL)
    try:
        yield database_connection
        database_connection.commit()
    except psycopg2.Error:
        database_connection.rollback()
        raise
    finally:
        database_connection.close()


def upsert_applicant(profile: ApplicantProfile) -> int:
    """Insert or update an applicant by email and return its identifier."""
    query = """
        INSERT INTO applicants (name, email, target_role, skills, resume_text)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (email) DO UPDATE SET
            name        = EXCLUDED.name,
            target_role = EXCLUDED.target_role,
            skills      = EXCLUDED.skills,
            resume_text = EXCLUDED.resume_text
        RETURNING id
    """
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(
                query,
                (profile.name, profile.email, profile.target_role, profile.skills, profile.resume_text),
            )
            return cursor.fetchone()[0]


def job_exists(job_url: str) -> bool:
    """Return whether a job URL is already stored."""
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM jobs WHERE job_url = %s", (job_url,))
            return cursor.fetchone() is not None


def insert_job(job: JobListing) -> int:
    """Insert a job or return the existing job identifier."""
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute("SELECT id FROM jobs WHERE job_url = %s", (job.job_url,))
            existing_job = cursor.fetchone()
            if existing_job:
                return existing_job[0]

            query = """
                INSERT INTO jobs (
                    title, company, location, job_url, requirements, seniority, contact_email
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            cursor.execute(
                query,
                (
                    job.title,
                    job.company,
                    job.location,
                    job.job_url,
                    job.requirements,
                    job.seniority,
                    job.contact_email,
                ),
            )
            return cursor.fetchone()[0]


def insert_application(job_id: int, applicant_id: int, email_draft: str) -> int:
    """Insert an application and return its identifier."""
    query = """
        INSERT INTO applications (job_id, applicant_id, email_draft)
        VALUES (%s, %s, %s)
        RETURNING id
    """
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(query, (job_id, applicant_id, email_draft))
            return cursor.fetchone()[0]


def update_application_status(application_id: int, status: str) -> None:
    """Update an application's status."""
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE applications SET status = %s WHERE id = %s",
                (status, application_id),
            )


def get_application_statuses(applicant_id: int) -> list[dict[str, str]]:
    """Return application statuses for a specific applicant with their job details."""
    query = """
        SELECT jobs.title, jobs.company, applications.status
        FROM applications
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.applicant_id = %s
        ORDER BY applications.id
    """
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(query, (applicant_id,))
            return [
                {"job title": row[0], "company": row[1], "send status": row[2]}
                for row in cursor.fetchall()
            ]


def log_step(
    run_id: str,
    node_name: str,
    input_summary: str,
    output_summary: str,
    status: str,
) -> None:
    """Store an agent execution step."""
    query = """
        INSERT INTO agent_logs (
            run_id, node_name, input_summary, output_summary, status
        )
        VALUES (%s, %s, %s, %s, %s)
    """
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(query, (run_id, node_name, input_summary, output_summary, status))


def applicant_has_applied(applicant_id: int, job_url: str) -> bool:
    """Return whether this applicant already has an application for the given job URL."""
    query = """
        SELECT 1 FROM applications a
        JOIN jobs j ON j.id = a.job_id
        WHERE a.applicant_id = %s AND j.job_url = %s
    """
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(query, (applicant_id, job_url))
            return cursor.fetchone() is not None


def save_session_state(thread_id: str, state: AgentState) -> None:
    """Upsert agent state for a session into the agent_sessions table."""
    query = """
        INSERT INTO agent_sessions (thread_id, state, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (thread_id) DO UPDATE SET
            state      = EXCLUDED.state,
            updated_at = now()
    """
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(query, (thread_id, state.model_dump_json()))


def load_session_state(thread_id: str) -> AgentState | None:
    """Return the persisted AgentState for a thread, or None if not found."""
    with get_connection() as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(
                "SELECT state FROM agent_sessions WHERE thread_id = %s", (thread_id,)
            )
            row = cursor.fetchone()
    if row is None:
        return None
    # psycopg2 deserializes JSONB to a Python dict automatically
    raw = row[0]
    if isinstance(raw, str):
        return AgentState.model_validate_json(raw)
    return AgentState.model_validate(raw)


