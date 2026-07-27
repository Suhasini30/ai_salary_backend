from litellm import completion
from app.core.config import settings
from app.prompt.system_prompt import SYSTEM_PROMPT


class LLMService:

    def chat(self, prompt, model=None):

        if model is None:
            model = settings.DEFAULT_MODEL

        # Determine API key based on model provider
        api_key = None
        if model and model.startswith("gemini/"):
            api_key = settings.GEMINI_API_KEY
        elif model and model.startswith("groq/"):
            api_key = settings.GROQ_API_KEY

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
            max_tokens=300,
            api_key=api_key,
        )

        for chunk in response:

            delta = chunk.choices[0].delta.content

            if delta:
                yield delta