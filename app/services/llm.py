"""
LLM streaming service.

Uses LiteLLM so the provider + model are fully configurable through env vars
(GROQ_MODEL / GEMINI_MODEL / XAI_MODEL / MISTRAL_MODEL / DEFAULT_MODEL), with
a fallback chain: if the primary model fails, it tries the next configured one.
This build uses the RAG system prompt (grounded, anti-hallucination).
"""
import logging

from litellm import acompletion

from app.core.config import settings
from app.prompt.rag_prompt import RAG_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class LLMService:
    async def chat(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.4,
        system_prompt: str | None = None,
    ):
        """
        Async generator that yields answer tokens one by one.
        Falls back across configured models when the primary errors out.
        """
        selected_model = settings.format_model_identifier(model or settings.DEFAULT_MODEL)

        fallback_models = [selected_model]
        for candidate in [settings.XAI_MODEL, settings.MISTRAL_MODEL,
                          settings.GROQ_MODEL, settings.GEMINI_MODEL]:
            cand_clean = settings.format_model_identifier(candidate)
            if cand_clean and cand_clean not in fallback_models:
                if "gemini" in cand_clean.lower() and not settings.GEMINI_API_KEY:
                    continue
                fallback_models.append(cand_clean)

        last_error = None

        for idx, current_model in enumerate(fallback_models, start=1):
            api_key = settings.get_api_key_for_model(current_model)
            if api_key is None and any(p in current_model.lower() for p in
                                       ("xai", "grok", "groq", "gemini", "mistral")):
                logger.info("Skipping %s (no API key configured).", current_model)
                continue

            try:
                logger.info("LLM streaming with '%s' (attempt %d/%d) ...",
                            current_model, idx, len(fallback_models))
                kwargs = {
                    "model": current_model,
                    "messages": [
                        {"role": "system", "content": system_prompt or RAG_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": True,
                    "temperature": temperature,
                    "max_tokens": 4096,
                }
                if api_key:
                    kwargs["api_key"] = api_key

                response = await acompletion(**kwargs)

                emitted = False
                async for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        emitted = True
                        yield delta

                if emitted:
                    return

            except Exception as exc:
                last_error = exc
                logger.warning("Model '%s' failed (%s). Trying fallback ...",
                               current_model, exc)

        yield f"\n\n[All LLM providers failed. Last error: {last_error}]"