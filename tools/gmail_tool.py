import base64
import logging
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow

from config.settings import GMAIL_CREDENTIALS_FILE

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_FILE = Path("token.json")
logger = logging.getLogger(__name__)


def get_gmail_service() -> Resource:
    """Return an authorized Gmail API service."""
    credentials: Credentials | None = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, SCOPES)
            credentials = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=credentials)


def send_email(to: str, subject: str, body: str, attachment_path: str | None = None) -> bool:
    """Send an email through Gmail, optionally with a file attachment."""
    if attachment_path is not None:
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders as email_encoders

        message: MIMEMultipart | MIMEText = MIMEMultipart("mixed")
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain", "utf-8"))

        attachment_file = Path(attachment_path)
        with open(attachment_file, "rb") as fh:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(fh.read())
        email_encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_file.name}"',
        )
        message.attach(part)
    else:
        message = MIMEText(body, "plain", "utf-8")
        message["To"] = to
        message["Subject"] = subject

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        get_gmail_service().users().messages().send(
            userId="me", body={"raw": encoded_message}
        ).execute()
    except (HttpError, OSError, RefreshError, TransportError):
        logger.exception("Failed to send email")
        return False

    return True
