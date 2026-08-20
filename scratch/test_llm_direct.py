"""
Direct test of the LLM streaming service — verifies whether token content
actually flows (my earlier SSE test showed empty token events, so I want to
rule out an LLM configuration problem vs. a test-parsing artifact).
"""
import asyncio
import sys

sys.path.insert(0, r"C:\Users\acer\Documents\sales_market_full_implementation\ai_salary_backend")

from app.core.config import settings
from app.services.llm import LLMService

async def main():
    print("Config:")
    print("  DEFAULT_MODEL:", settings.DEFAULT_MODEL)
    print("  GROQ_MODEL:", getattr(settings, "GROQ_MODEL", None))
    print("  GROQ_API_KEY set:", bool(settings.GROQ_API_KEY))

    svc = LLMService()
    chunks = []
    try:
        async for chunk in svc.chat("Say the word 'OK' and nothing else."):
            chunks.append(chunk)
            print(f"  chunk: {chunk!r}")
    except Exception as e:
        print(f"  LLM error: {type(e).__name__}: {e}")

    print(f"\nTotal chunks: {len(chunks)}, total chars: {sum(len(c) for c in chunks)}")
    print("RESULT:", "PASS — text is streaming" if sum(len(c) for c in chunks) > 0 else "FAIL — empty stream")

asyncio.run(main())