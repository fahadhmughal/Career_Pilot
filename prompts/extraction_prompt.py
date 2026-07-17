EXTRACTION_PROMPT = """Extract a JobListing from the raw search result below.

Raw result:
{raw_result}

Return only strict JSON matching this schema:
{{
  "title": "string",
  "company": "string",
  "location": "string",
  "job_url": "string",
  "requirements": "string",
  "seniority": "string",
  "contact_email": "string or null"
}}

Rules:
- contact_email: scan every word in the text for an @ symbol. If any email address is present, use it. If multiple, use the first. Only use null if no email address exists anywhere in the text.
- For all other required string fields, use an empty string if the value is not present.
- Do not invent any data. Use only what is in the raw result."""

