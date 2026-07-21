import time
from app.services.llm import chat

MAX_RETRIES = 3
RETRY_DELAY = 2

def retry(model: str, user: str):

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            print(f"Attempt {attempt} using {model}")

            return chat(model, user)

        except Exception as e:

            last_exception = e
            print(f"Attempt {attempt} failed: {e}")

            if attempt < MAX_RETRIES:
                print(f"Retrying after {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)

    raise last_exception