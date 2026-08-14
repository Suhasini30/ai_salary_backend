import logging
import time

import httpx
from langchain_core.tools import tool

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RESULTS = 8
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2


def _format_salary(job):
    min_salary = job.get("job_min_salary")
    max_salary = job.get("job_max_salary")
    currency = job.get("job_salary_currency") or ""

    if not min_salary and not max_salary:
        return ""

    min_salary = min_salary or 0
    max_salary = max_salary or 0
    return f" | Salary: {min_salary:,.0f}-{max_salary:,.0f} {currency}".rstrip()


def _format_results(jobs):
    if not jobs:
        return "No live job listings found for this query."

    lines = []
    for i, job in enumerate(jobs[:MAX_RESULTS], start=1):
        title = job.get("job_title") or "Untitled role"
        company = job.get("employer_name") or "Unknown company"
        location = " / ".join(
            filter(None, [
                job.get("job_city"),
                job.get("job_state"),
                job.get("job_country"),
            ])
        ) or "Remote/Unknown"
        salary = _format_salary(job)
        apply_link = job.get("job_apply_link") or ""

        lines.append(
            f"{i}. {title} at {company} - {location}{salary}"
            + (f" | Apply: {apply_link}" if apply_link else "")
        )

    return "\n".join(lines)


def _pick_date_posted(query):
    """Map recency phrases in the query to JSearch's date_posted filter."""
    q = query.lower()

    if any(k in q for k in ("24", "today", "24-hour", "24 hour", "24hr", "24 hrs",
                            "last day", "last 24", "past day", "past 24")):
        return "today"
    if any(k in q for k in ("3 day", "three day", "72 hour", "72hr", "last 3")):
        return "3days"
    if any(k in q for k in ("week", "weekly", "7 day", "seven day", "last week")):
        return "week"
    if any(k in q for k in ("month", "monthly", "30 day", "this month")):
        return "month"

    return "all"


def _pick_country(query):
    """Map country names/cities in the query to a JSearch country code."""
    q = query.lower()

    india = ("india", "chennai", "bangalore", "bengaluru", "hyderabad", "mumbai",
             "delhi", "pune", "kolkata", "gurgaon", "noida", "ahmedabad")
    uk = ("uk", "united kingdom", "london", "manchester", "glasgow", "edinburgh")
    canada = ("canada", "toronto", "vancouver", "montreal", "ottawa", "calgary")

    if any(k in q for k in india):
        return "in"
    if any(k in q for k in uk):
        return "gb"
    if any(k in q for k in canada):
        return "ca"

    return "us"


def _call_jsearch(query):
    if not settings.JSEARCH_API_KEY:
        raise RuntimeError(
            "JSEARCH_API_KEY is not set. Add it to .env to enable live job search."
        )

    headers = {
        "x-rapidapi-key": settings.JSEARCH_API_KEY,
        "x-rapidapi-host": settings.RAPIDAPI_HOST,
    }

    params = {
        "query": query,
        "page": "1",
        "num_pages": "1",
        "country": _pick_country(query),
        "date_posted": _pick_date_posted(query),
    }

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.get(
                    f"{settings.JSEARCH_BASE_URL}/search-v2",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json().get("data") or {}
                jobs = data.get("jobs") if isinstance(data, dict) else (data or [])
                return _format_results(jobs)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                if attempt >= MAX_RETRIES:
                    logger.warning("JSearch request failed after %d attempts: %s", attempt + 1, e)
                    raise
                wait = 1.5 * (2 ** attempt)
                logger.info("JSearch request attempt %d failed (%s); retrying in %.1fs...", attempt + 1, e, wait)
                time.sleep(wait)


@tool("JSearchJobSearch", description="Search LIVE current job postings using the JSearch (RapidAPI) jobs API. Use it when the user wants job openings, companies hiring now, or live listings. Returns formatted listings with company, location, salary and apply link.")
def jsearch_tool(query: str) -> str:
    """Search live job postings. Pass the user's job search query."""
    try:
        return _call_jsearch(query)
    except Exception as e:
        logger.warning("JSearch call failed: %s", e, exc_info=True)
        return f"Live job search is currently unavailable: {e}"


class JSearchTool:
    """Thin wrapper so the orchestrator can invoke the LangChain tool."""

    def search(self, query):
        # LangChain @tool .invoke() requires a dict for named-arg tools
        return jsearch_tool.invoke({"query": query})

    def search_results(self, query):
        """Returns (formatted_text, ok_flag). ok_flag is False on failure."""
        try:
            result = _call_jsearch(query)
            return result, True
        except Exception as e:
            logger.warning("JSearch call failed: %s", e, exc_info=True)
            return f"Live job search is currently unavailable: {e}", False