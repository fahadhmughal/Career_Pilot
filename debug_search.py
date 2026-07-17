"""Debug script - runs each step of fetch_one_job and prints results."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.web_search import search_jobs, scrape_email_from_url, PAKISTAN_JOB_DOMAINS
from graph.nodes import llm, _clean_email, _is_pakistan_location, PAKISTAN_LOCATION_KEYWORDS
from prompts.extraction_prompt import EXTRACTION_PROMPT
from schemas.models import JobListing
from pydantic import ValidationError

CRITERIA = "AI Engineer intern"

print("=" * 60)
print(f"Criteria: {CRITERIA}")
print("=" * 60)

# Step 1: Search
query = f"{CRITERIA} jobs in Pakistan hiring"
print(f"\n[1] Tavily search (Pakistani domains): {query!r}")
results = search_jobs(query, max_results=15, include_domains=PAKISTAN_JOB_DOMAINS)
print(f"    -> {len(results)} results from PK domains")

if not results:
    fallback_query = f"{CRITERIA} jobs Pakistan"
    print(f"\n[1b] Fallback search: {fallback_query!r}")
    results = search_jobs(fallback_query, max_results=15)
    print(f"    -> {len(results)} results from fallback")

if not results:
    print("\nNO RESULTS AT ALL FROM TAVILY. Check API key / quota.")
    sys.exit(1)

# Step 2: Extract each result
print(f"\n[2] Extracting {len(results)} results...\n")
for i, raw in enumerate(results, 1):
    url = raw.get("url", "")
    from_pk = any(d in url for d in PAKISTAN_JOB_DOMAINS)
    print(f"  [{i}] URL: {url}")
    print(f"       from_pk_domain={from_pk}")

    try:
        job = llm.with_structured_output(JobListing).invoke(
            EXTRACTION_PROMPT.format(raw_result=raw)
        )
        job.contact_email = _clean_email(job.contact_email)
    except (Exception, ValidationError) as e:
        print(f"       LLM extraction FAILED: {e}")
        continue

    pk_location = _is_pakistan_location(job.location)
    print(f"       title={job.title!r}  company={job.company!r}")
    print(f"       location={job.location!r}  pk_location={pk_location}")
    print(f"       contact_email={job.contact_email!r}")

    # Would this pass the location filter?
    passes_location = from_pk or pk_location
    print(f"       passes_location_filter={passes_location}")

    if passes_location and job.contact_email is None:
        print(f"       -> scraping {url} for email...")
        scraped = scrape_email_from_url(url)
        print(f"       -> scraped email: {scraped!r}")
        job.contact_email = scraped

    verdict = "WOULD USE" if passes_location and job.contact_email else "SKIP"
    print(f"       VERDICT: {verdict}\n")
