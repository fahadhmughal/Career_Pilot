import re
import urllib.request

from tavily import TavilyClient

from config.settings import TAVILY_API_KEY

PAKISTAN_JOB_DOMAINS = [
    "rozee.pk",
    "indeed.com.pk",
    "mustakbil.com",
    "bayrozgar.com",
    "linkedin.com",
]

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_IGNORED_EMAIL_DOMAINS = {"example.com", "sentry.io", "w3.org", "schema.org"}


def search_jobs(query: str, max_results: int = 10, include_domains: list[str] | None = None) -> list[dict]:
    """Search for jobs with Tavily, optionally biased toward given domains."""
    client = TavilyClient(api_key=TAVILY_API_KEY)
    response = client.search(
        query=query,
        max_results=max_results,
        include_domains=include_domains,
        include_raw_content=True,
    )
    return response["results"]


def scrape_email_from_url(url: str, timeout: int = 8) -> str | None:
    """Fetch the page at url and return the first real contact email found, or None."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CareerPilot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    for match in _EMAIL_PATTERN.finditer(html):
        email = match.group(0)
        domain = email.split("@", 1)[1].lower()
        if domain not in _IGNORED_EMAIL_DOMAINS and not domain.startswith("example"):
            return email
    return None