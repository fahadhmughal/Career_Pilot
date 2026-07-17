EMAIL_PROMPT = """Write a professional job application email for the applicant below.

Applicant profile:
{applicant_profile}

Job listing:
{job_listing}

Structure the email body exactly as follows, separating each part with a blank line (\\n\\n):
1. Greeting: "Dear Hiring Team," (or the contact name if available)
2. Opening sentence: state the specific role and your single strongest matching qualification
3. Body (2-3 sentences): reference concrete overlaps between the applicant's skills and the job requirements. Be specific, not generic.
4. Closing sentence: express interest in discussing further and mention the attached resume
5. Sign-off on its own line: "Best regards," followed by the applicant's full name on the next line

Rules:
- The body field must contain literal blank lines (\\n\\n) between each of the 5 parts above, so it reads as a properly formatted email, not one paragraph.
- Keep the total email under 250 words
- Do not invent qualifications not present in the profile
- Do not use filler phrases like "I am excited to apply" or "I believe I would be a great fit"

Return subject as a concise professional subject line starting with "Application:"."""

REVISION_PROMPT = """Revise the job application email below based on the applicant's feedback.

Current email body:
{previous_draft}

Feedback to apply:
{feedback}

Maintain the same structure, with each part separated by a blank line (\\n\\n):
1. Greeting
2. Opening with role and top qualification
3. Specific skills body (2-3 sentences)
4. Closing with call to action
5. Sign-off on its own line, followed by the applicant's name on the next line

Apply the feedback precisely. Keep under 250 words. Do not add qualifications not in the original.
The job URL is: {job_url}

Return subject as a concise professional subject line starting with "Application:"."""