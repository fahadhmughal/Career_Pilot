from os import environ

from dotenv import load_dotenv

load_dotenv()

_REQUIRED_VARIABLES = (
    "DATABASE_URL",
    "TAVILY_API_KEY",
    "SHEET_ID",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "GMAIL_CREDENTIALS_FILE",
    "GROQ_API_KEY",
)
_missing_variables = [name for name in _REQUIRED_VARIABLES if not environ.get(name)]

if _missing_variables:
    missing = ", ".join(_missing_variables)
    raise RuntimeError(f"Missing required environment variables: {missing}")

DATABASE_URL: str = environ["DATABASE_URL"]
TAVILY_API_KEY: str = environ["TAVILY_API_KEY"]
SHEET_ID: str = environ["SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_FILE: str = environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
GMAIL_CREDENTIALS_FILE: str = environ["GMAIL_CREDENTIALS_FILE"]
GROQ_API_KEY: str = environ["GROQ_API_KEY"]
GROQ_MODEL: str = environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Collect all provided Groq keys for round-robin fallback.
GROQ_API_KEYS: list[str] = [GROQ_API_KEY]
for _slot in ("GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4", "GROQ_API_KEY_5"):
    _val = environ.get(_slot, "").strip()
    if _val:
        GROQ_API_KEYS.append(_val)
