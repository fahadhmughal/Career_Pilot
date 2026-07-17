from pathlib import Path

from docx import Document
from pypdf import PdfReader


def parse_resume(file_path: str) -> str:
    """Extract plain text from a PDF or DOCX resume."""
    extension = Path(file_path).suffix.lower()

    if extension == ".pdf":
        reader = PdfReader(file_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if extension == ".docx":
        document = Document(file_path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    raise ValueError(f"Unsupported resume file extension: {extension}")
