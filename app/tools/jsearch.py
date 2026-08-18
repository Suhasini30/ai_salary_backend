import logging
import time

import httpx
from langchain_core.tools import tool

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RESULTS = 8
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2

# Words that add no search value (JSearch matches keywords).
FILLER_WORDS = {
    "find", "show", "me", "current", "available", "right", "now", "any",
    "the", "in", "for", "please", "get", "list", "some", "today", "live",
    "looking", "what", "are", "can", "you", "give", "need", "want", "find",
    "jobs", "job", "openings", "opening", "position", "positions", "vacancy",
    "vacancies", "hiring", "roles", "role", "postings", "posting", "with",
    "and", "or", "to", "at", "a", "me", "latest", "recent", "of", "about",
}

# Country/city tokens used both for the JSearch country filter and to strip
# location words out of the keyword query so "AI jobs in germany" searches "ai".
COUNTRY_TOKENS = {
    "us": ["usa", "america", "united states", "new york", "san francisco", "california",
           "texas", "washington", "seattle", "chicago", "arlington", "dc"],
    "in": ["india", "chennai", "bangalore", "bengaluru", "hyderabad", "mumbai",
           "delhi", "pune", "kolkata", "gurgaon", "noida", "ahmedabad"],
    "gb": ["uk", "united kingdom", "london", "manchester", "glasgow", "edinburgh"],
    "ca": ["canada", "toronto", "vancouver", "montreal", "ottawa", "calgary"],
    "de": ["germany", "berlin", "munich", "münchen", "frankfurt", "hamburg", "cologne", "stuttgart"],
    "fr": ["france", "paris", "lyon", "toulouse", "bordeaux", "nice"],
    "es": ["spain", "madrid", "barcelona", "valencia", "seville"],
    "au": ["australia", "sydney", "melbourne", "perth", "brisbane"],
    "ie": ["ireland", "dublin", "cork"],
    "nl": ["netherlands", "amsterdam", "rotterdam", "the hague", "eindhoven"],
    "ch": ["switzerland", "zurich", "geneva", "basel"],
    "sg": ["singapore"],
    "ae": ["uae", "dubai", "abu dhabi"],
}


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
        return ""

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
    for code, tokens in COUNTRY_TOKENS.items():
        if any(k in q for k in tokens):
            return code
    return ""


def _is_location_word(tok):
    for tokens in COUNTRY_TOKENS.values():
        if any(w == tok for w in tokens):
            return True
    return False


def _clean_query(query):
    """Drop filler and location words so JSearch gets the real keywords."""
    q = query.lower()
    kept = []
    for tok in q.split():
        if tok in FILLER_WORDS:
            continue
        if _is_location_word(tok):
            continue
        kept.append(tok)
    return " ".join(kept) if kept else ""


def _fetch_jobs(params, headers):
    """Single HTTP attempt (with retry & backoff). Returns the jobs list."""
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
                return jobs or []
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                if attempt >= MAX_RETRIES:
                    logger.warning("JSearch request failed after %d attempts: %s", attempt + 1, e)
                    raise
                wait = 1.5 * (2 ** attempt)
                logger.info("JSearch request attempt %d failed (%s); retrying in %.1fs...", attempt + 1, e, wait)
                time.sleep(wait)


def _call_jsearch(query):
    if not settings.JSEARCH_API_KEY:
        raise RuntimeError(
            "JSEARCH_API_KEY is not set. Add it to .env to enable live job search."
        )

    headers = {
        "x-rapidapi-key": settings.JSEARCH_API_KEY,
        "x-rapidapi-host": settings.RAPIDAPI_HOST,
    }

    country = _pick_country(query)
    base = _clean_query(query) or "jobs"
    date_posted = _pick_date_posted(query)

    last_error = None

    # Try increasingly broad searches until something comes back:
    # 1. cleaned keywords + detected country
    # 2. cleaned keywords, global
    # 3. original query, global
    attempts = []
    if country:
        attempts.append((base, country))
    attempts.append((base, ""))
    attempts.append((query, ""))

    seen = set()
    for keywords, cntry in attempts:
        key = (keywords, cntry)
        if key in seen:
            continue
        seen.add(key)

        params = {
            "query": keywords,
            "page": "1",
            "num_pages": "1",
        }
        if cntry:
            params["country"] = cntry
        if date_posted:
            params["date_posted"] = date_posted

        try:
            jobs = _fetch_jobs(params, headers)
        except Exception as e:
            last_error = e
            logger.warning("JSearch attempt (%r, %r) failed: %s", keywords, cntry, e)
            continue

        if jobs:
            logger.info("JSearch returned %d jobs for query=%r country=%r", len(jobs), keywords, cntry)
            return _format_results(jobs)

    if last_error:
        raise last_error
    return "No live job listings found for this query."


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