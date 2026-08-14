"""
Full end-to-end debug script for JSearch workflow.
Run: venv\\Scripts\\python.exe debug_jsearch.py
"""

import os
import sys
import json
import traceback

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

issues = []

# ─────────────────────────────────────────────
# STEP 1: dotenv
# ─────────────────────────────────────────────
print("\n" + "="*55)
print("  STEP 1: dotenv / environment loading")
print("="*55)
try:
    from dotenv import load_dotenv
    loaded = load_dotenv(override=True)
    print(f"{PASS} dotenv loaded: {loaded}")
except Exception as e:
    print(f"{FAIL} dotenv failed: {e}")
    issues.append(f"dotenv import/load failed: {e}")

raw_key = os.getenv("JSEARCH_API_KEY", "")
print(f"  Raw JSEARCH_API_KEY  : {repr(raw_key)}")
print(f"  Key length           : {len(raw_key)}")

if not raw_key:
    print(f"{FAIL} JSEARCH_API_KEY is empty or missing in .env")
    issues.append("JSEARCH_API_KEY is not set in .env")
elif raw_key != raw_key.strip():
    print(f"{FAIL} JSEARCH_API_KEY has leading/trailing whitespace!")
    issues.append(f"JSEARCH_API_KEY has whitespace: {repr(raw_key)}")
else:
    print(f"{PASS} JSEARCH_API_KEY has no whitespace")

# ─────────────────────────────────────────────
# STEP 2: settings config
# ─────────────────────────────────────────────
print("\n" + "="*55)
print("  STEP 2: app.core.config Settings")
print("="*55)
try:
    from app.core.config import settings
    print(f"  JSEARCH_API_KEY  : {repr(settings.JSEARCH_API_KEY)}")
    print(f"  RAPIDAPI_HOST    : {repr(settings.RAPIDAPI_HOST)}")
    print(f"  JSEARCH_BASE_URL : {repr(settings.JSEARCH_BASE_URL)}")
    print(f"  ROUTER_MODEL     : {repr(settings.ROUTER_MODEL)}")
    print(f"  GROQ_MODEL       : {repr(settings.GROQ_MODEL)}")
    print(f"  GEMINI_MODEL     : {repr(settings.GEMINI_MODEL)}")
    print(f"  DEFAULT_MODEL    : {repr(settings.DEFAULT_MODEL)}")
    print(f"  ROUTER_MIN_CONF  : {settings.ROUTER_MIN_CONFIDENCE}")

    if settings.JSEARCH_API_KEY != settings.JSEARCH_API_KEY.strip():
        print(f"{FAIL} settings.JSEARCH_API_KEY still has whitespace!")
        issues.append("settings.JSEARCH_API_KEY has whitespace after load")
    else:
        print(f"{PASS} settings.JSEARCH_API_KEY is clean")

    if not settings.JSEARCH_API_KEY:
        issues.append("settings.JSEARCH_API_KEY is empty/None")
    if not settings.ROUTER_MODEL:
        print(f"{WARN} ROUTER_MODEL is empty -- will fall back to GROQ_MODEL")
        issues.append("ROUTER_MODEL is not set (using GROQ_MODEL as fallback -- OK)")
except Exception as e:
    print(f"{FAIL} settings import failed: {e}")
    issues.append(f"Settings config error: {e}")
    traceback.print_exc()

# ─────────────────────────────────────────────
# STEP 3: Raw HTTP call to JSearch
# ─────────────────────────────────────────────
print("\n" + "="*55)
print("  STEP 3: Raw HTTP call to JSearch API")
print("="*55)
api_ok = False
try:
    import httpx
    key = settings.JSEARCH_API_KEY
    host = settings.RAPIDAPI_HOST
    base_url = settings.JSEARCH_BASE_URL

    headers = {
        "x-rapidapi-key": key,
        "x-rapidapi-host": host,
    }
    params = {
        "query": "python developer jobs",
        "page": "1",
        "num_pages": "1",
        "country": "us",
        "date_posted": "all",
    }
    url = f"{base_url}/search-v2"
    print(f"  URL     : {url}")
    print(f"  Headers : x-rapidapi-key={repr(key[:8])}... x-rapidapi-host={host}")
    print(f"  Params  : {params}")

    with httpx.Client(timeout=20.0) as client:
        resp = client.get(url, params=params, headers=headers)
        print(f"\n  Response Status : {resp.status_code}")
        print(f"  Response Body   : {resp.text[:500]}")

        if resp.status_code == 200:
            payload = resp.json().get("data", {})
            data = payload.get("jobs") if isinstance(payload, dict) else (payload or [])
            print(f"\n{PASS} JSearch returned {len(data)} jobs")
            if data:
                j = data[0]
                print(f"  First job: {j.get('job_title')} at {j.get('employer_name')}")
            api_ok = True
        elif resp.status_code == 403:
            print(f"\n{FAIL} 403 Forbidden -- API key is invalid or not authenticated")
            issues.append("JSearch returned 403: API key rejected by RapidAPI")
        elif resp.status_code == 404:
            msg = resp.json().get("message", "")
            if "does not exist" in msg and "search-v2" not in msg:
                print(f"\n{FAIL} 404 -- API key is NOT subscribed to JSearch on RapidAPI")
                issues.append("JSearch 404: RapidAPI key not subscribed. Visit https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch and subscribe.")
            else:
                print(f"\n{FAIL} 404 endpoint not found: {msg}")
                issues.append(f"JSearch 404: {msg}")
        elif resp.status_code == 429:
            print(f"\n{FAIL} 429 -- Rate limit exceeded (monthly quota hit)")
            issues.append("JSearch 429: Monthly request quota exceeded on RapidAPI")
        else:
            print(f"\n{FAIL} Unexpected status {resp.status_code}")
            issues.append(f"JSearch unexpected HTTP {resp.status_code}: {resp.text[:200]}")
except Exception as e:
    print(f"{FAIL} HTTP call threw exception: {e}")
    issues.append(f"JSearch HTTP call exception: {e}")
    traceback.print_exc()

# ─────────────────────────────────────────────
# STEP 4: JSearchTool wrapper
# ─────────────────────────────────────────────
print("\n" + "="*55)
print("  STEP 4: JSearchTool wrapper (search_results)")
print("="*55)
try:
    from app.tools.jsearch import JSearchTool
    tool = JSearchTool()
    text, ok = tool.search_results("python developer jobs")
    print(f"  ok flag  : {ok}")
    print(f"  result   : {text[:300]}")
    if ok:
        print(f"{PASS} JSearchTool.search_results() worked")
    else:
        print(f"{FAIL} JSearchTool.search_results() returned ok=False")
        issues.append(f"JSearchTool.search_results() failed: {text}")
except Exception as e:
    print(f"{FAIL} JSearchTool import/call failed: {e}")
    issues.append(f"JSearchTool exception: {e}")
    traceback.print_exc()

# ─────────────────────────────────────────────
# STEP 5: LLM Router classification
# ─────────────────────────────────────────────
print("\n" + "="*55)
print("  STEP 5: LLM Router (classify job-search query)")
print("="*55)
try:
    from app.routers.llm_router import LLMRouter
    router = LLMRouter()
    decision = router.classify("Find me python developer jobs right now")
    print(f"  intent     : {decision['intent']}")
    print(f"  confidence : {decision['confidence']}")
    print(f"  reason     : {decision['reason']}")
    if decision["intent"] in ("TOOL", "BOTH"):
        print(f"{PASS} Router correctly classified as {decision['intent']}")
    else:
        print(f"{WARN} Router returned '{decision['intent']}' -- expected TOOL or BOTH")
        issues.append(f"Router classified job-search query as '{decision['intent']}' instead of TOOL")
except Exception as e:
    print(f"{FAIL} LLMRouter failed: {e}")
    issues.append(f"LLMRouter exception: {e}")
    traceback.print_exc()

# ─────────────────────────────────────────────
# STEP 6: LangChain @tool invoke
# ─────────────────────────────────────────────
print("\n" + "="*55)
print("  STEP 6: LangChain @tool .invoke() call")
print("="*55)
try:
    from app.tools.jsearch import jsearch_tool
    result = jsearch_tool.invoke({"query": "python developer jobs"})
    print(f"  Result: {result[:300]}")
    if "unavailable" in result.lower():
        print(f"{WARN} Tool returned fallback message (API issue, not code issue)")
        issues.append("jsearch_tool.invoke() returned fallback -- JSearch API not working")
    else:
        print(f"{PASS} jsearch_tool.invoke() returned real results")
except Exception as e:
    print(f"{FAIL} jsearch_tool.invoke() threw exception: {e}")
    issues.append(f"jsearch_tool.invoke() exception: {e}")
    traceback.print_exc()

# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────
print("\n" + "="*55)
print("  DEBUG SUMMARY")
print("="*55)
if issues:
    print(f"  Found {len(issues)} issue(s):\n")
    for i, iss in enumerate(issues, 1):
        print(f"  {i}. {iss}")
else:
    print(f"  No issues found! JSearch workflow is healthy.")
print("="*55 + "\n")
