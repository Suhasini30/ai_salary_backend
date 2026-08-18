import logging
from litellm import completion
from app.core.config import settings
from app.prompt.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class LLMService:

    def chat(self, prompt, model=None):
        raw_model = model or settings.DEFAULT_MODEL
        selected_model = settings.format_model_identifier(raw_model)

        # Build fallback list of models (excluding Vertex AI / Gemini if not configured)
        fallback_models = [selected_model]
        for candidate in [settings.XAI_MODEL, settings.MISTRAL_MODEL, settings.GROQ_MODEL, settings.DEFAULT_MODEL]:
            if candidate:
                cand_clean = settings.format_model_identifier(candidate)
                if cand_clean not in fallback_models:
                    fallback_models.append(cand_clean)

        last_error = None
        for idx, current_raw in enumerate(fallback_models):
            if not current_raw:
                continue

            current_model = settings.format_model_identifier(current_raw)
            # Skip Vertex AI / Gemini models if disabled / not configured
            if "gemini" in current_model.lower() or "vertex" in current_model.lower():
                if not settings.GEMINI_API_KEY:
                    logger.info("Skipping Vertex AI / Gemini model '%s' (disabled / not configured).", current_model)
                    continue

            api_key = settings.get_api_key_for_model(current_model)
            if api_key is None and any(p in current_model.lower() for p in ["xai", "grok", "groq", "gemini", "mistral"]):
                logger.info("Skipping model '%s' (no API key configured).", current_model)
                continue

            try:
                logger.info(
                    "LiteLLM chat streaming invoking model: '%s' (attempt %d/%d)...",
                    current_model, idx + 1, len(fallback_models)
                )

                kwargs = {
                    "model": current_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": True,
                    "temperature": 0.7,
                    "max_tokens": 4000,
                }
                if api_key:
                    kwargs["api_key"] = api_key

                response = completion(**kwargs)

                emitted = False
                for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        emitted = True
                        yield delta

                if emitted:
                    return

            except Exception as e:
                last_error = e
                logger.warning(
                    "Chat generation failed on model '%s' (%s). Trying fallback...",
                    current_model, e
                )

        yield f"\n[Error: All LLM models in fallback chain failed. Last error: {last_error}]"