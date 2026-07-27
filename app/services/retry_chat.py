import time

from app.services.llm import LLMService

MAX_RETRIES = 3
RETRY_DELAY = 2

_llm_service = LLMService()


def retry(model: str, user: str):
    """
    Retries LLMService.chat() up to MAX_RETRIES times.
    LLMService.chat() streams chunks, so we join them into a full
    string here — this function returns complete text, not a generator.
    """

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            print(f"Attempt {attempt} using {model}")

            # LLMService.chat(prompt, model) — prompt first, matching its signature
            return "".join(_llm_service.chat(user, model))

        except Exception as e:

            last_exception = e
            print(f"Attempt {attempt} failed: {e}")

            if attempt < MAX_RETRIES:
                print(f"Retrying after {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)

    raise last_exception