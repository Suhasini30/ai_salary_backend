from litellm import completion
from app.core.config import settings
from app.prompt.system_prompt import SYSTEM_PROMPT


class LLMService:

    def chat(self, prompt, model=None):

        if model is None:
            model = settings.DEFAULT_MODEL

        response = completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            stream=True,
            temperature=0.7,
            max_tokens=300
        )

        for chunk in response:

            delta = chunk.choices[0].delta.content

            if delta:
                yield delta