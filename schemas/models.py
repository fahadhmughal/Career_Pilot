from pydantic import BaseModel, Field


class ApplicantProfile(BaseModel):
    name: str
    email: str
    target_role: str
    skills: list[str]
    resume_text: str


class JobListing(BaseModel):
    title: str
    company: str
    location: str
    job_url: str
    requirements: str
    seniority: str
    contact_email: str | None = None


class EmailDraft(BaseModel):
    job_url: str
    subject: str
    body: str


class AgentState(BaseModel):
    applicant: ApplicantProfile | None = None
    applicant_id: int | None = None
    search_criteria: str = ""
    resume_path: str = ""
    raw_results: list[dict] = Field(default_factory=list)
    found_jobs: list[JobListing] = Field(default_factory=list)
    new_jobs: list[JobListing] = Field(default_factory=list)
    job_ids: dict[str, int] = Field(default_factory=dict)
    drafts: list[EmailDraft] = Field(default_factory=list)
    approved_drafts: list[EmailDraft] = Field(default_factory=list)
    shown_job_urls: list[str] = Field(default_factory=list)
    current_job: JobListing | None = None
    current_draft: EmailDraft | None = None
    error: str | None = None
