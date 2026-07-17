from datetime import datetime

import gspread

from config.settings import GOOGLE_SERVICE_ACCOUNT_FILE, SHEET_ID
from schemas.models import JobListing


def log_job_to_sheet(job: JobListing, status: str) -> None:
    """Append a job record to the configured spreadsheet."""
    client = gspread.service_account(filename=GOOGLE_SERVICE_ACCOUNT_FILE)
    worksheet = client.open_by_key(SHEET_ID).sheet1

    if not worksheet.row_values(1):
        worksheet.append_row(["Title", "Company", "Location", "URL", "Status", "Date"])

    worksheet.append_row(
        [
            job.title,
            job.company,
            job.location,
            job.job_url,
            status,
            datetime.now().isoformat(sep=" ", timespec="seconds"),
        ]
    )
