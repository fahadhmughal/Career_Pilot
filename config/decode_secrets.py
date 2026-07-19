import base64
import os


def write_secret_files() -> None:
    try:
        import streamlit as st
    except ImportError:
        return

    if "GOOGLE_SERVICE_ACCOUNT_B64" not in st.secrets:
        return

    _b64_files = {
        "GOOGLE_SERVICE_ACCOUNT_B64": "service_account.json",
        "GMAIL_CREDENTIALS_B64": "credentials.json",
        "GMAIL_TOKEN_B64": "token.json",
    }

    for secret_key, filename in _b64_files.items():
        if not os.path.exists(filename):
            data = base64.b64decode(st.secrets[secret_key])
            with open(filename, "wb") as f:
                f.write(data)

    _env_keys = ["DATABASE_URL", "TAVILY_API_KEY", "GROQ_API_KEY", "SHEET_ID"]
    for key in _env_keys:
        if key not in os.environ and key in st.secrets:
            os.environ[key] = st.secrets[key]
