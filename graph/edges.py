from schemas.models import AgentState


def should_continue_after_research(state: AgentState) -> str:
    """Route research results to extraction or end the run."""
    if state.raw_results:
        return "extract"

    state.error = "No jobs found. Broaden your search criteria and try again."
    return "end"


def should_continue_after_extract(state: AgentState) -> str:
    """Route extracted jobs to storage or end the run."""
    if state.found_jobs:
        return "store"

    return "end"
