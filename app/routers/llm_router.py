import json
import logging

from litellm import acompletion

from app.core.config import settings
from app.prompt.router_prompt import ROUTER_SYSTEM_PROMPT, ROUTER_USER_PROMPT

logger = logging.getLogger(__name__)

VALID_INTENTS = {"RAG", "TOOL", "BOTH", "GENERAL"}


def _extract_json(text):
    """Pull the first JSON object out of a model response, tolerating fences."""
    if not text:
        return None

    text = text.strip()

    # Drop markdown code fences if present
    fence = text.find("```")
    if fence != -1:
        text = text[fence + 3:]
        end = text.rfind("```")
        if end != -1:
            text = text[:end]

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    return text[start:end + 1]


class LLMRouter:
    """
    Classifies a user question into RAG / TOOL / BOTH / GENERAL with multi-model fallback logic.
    Attempts primary router model first, and cascades through configured fallback models (e.g. xAI Grok, Gemini, Groq)
    if errors, rate-limits, or unparseable outputs occur.

    NOTE: classify() is async and calls litellm.acompletion() directly (no thread offload).
    This must be awaited from an async context — do not wrap it in asyncio.run().
    """

    def __init__(self, fallback_models=None):
        self.fallback_models = fallback_models or settings.ROUTER_FALLBACK_MODELS

    async def classify(self, question: str):
        decision = {
            "intent": "GENERAL",
            "confidence": 0.0,
            "reason": "Router output was unparseable",
        }

        # Build candidate fallback models list
        candidate_models = list(self.fallback_models) if self.fallback_models else [settings.ROUTER_MODEL]
        last_error = None
        succeeded = False

        for idx, raw_model in enumerate(candidate_models):
            if not raw_model:
                continue

            model = settings.format_model_identifier(raw_model)
            # Skip Vertex AI / Gemini models if disabled or not configured
            if "gemini" in model.lower() or "vertex" in model.lower():
                if not settings.GEMINI_API_KEY:
                    logger.info("Skipping Vertex AI / Gemini model '%s' (disabled / not configured).", model)
                    continue

            api_key = settings.get_api_key_for_model(model)
            # If the model requires an API key and it's missing/empty, skip to next candidate
            if api_key is None and any(p in model.lower() for p in ["xai", "grok", "groq", "gemini", "mistral"]):
                logger.info("Skipping model '%s' (no API key configured).", model)
                continue

            try:
                logger.info(
                    "LiteLLM router invoking model: '%s' (fallback tier %d/%d)...",
                    model, idx + 1, len(candidate_models)
                )

                kwargs = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                        {"role": "user", "content": ROUTER_USER_PROMPT.format(question=question)},
                    ],
                    "temperature": 0,
                    "max_tokens": 512,
                    "timeout": 30.0,
                }
                if api_key:
                    kwargs["api_key"] = api_key

                response = await acompletion(**kwargs)

                raw = response.choices[0].message.content or ""
                extracted = _extract_json(raw)
                if not extracted:
                    raise ValueError(f"No JSON object found in response: {raw!r}")

                try:
                    payload = json.loads(extracted)
                except json.JSONDecodeError as je:
                    raise ValueError(f"Model returned truncated/malformed JSON. Last payload: {raw!r} | error: {je}") from je

                intent = str(payload.get("intent") or "").upper()
                confidence = float(payload.get("confidence") or 0.0)

                if intent not in VALID_INTENTS:
                    intent = "GENERAL"

                decision = {
                    "intent": intent,
                    "confidence": max(0.0, min(1.0, confidence)),
                    "reason": str(payload.get("reason") or ""),
                    "routed_by": model,
                }

                logger.info(
                    "Successfully classified prompt with '%s' -> intent=%s, confidence=%.2f",
                    model, decision["intent"], decision["confidence"]
                )
                succeeded = True
                break

            except Exception as e:
                last_error = e
                logger.warning(
                    "Router model '%s' failed (%s). Attempting next fallback model in chain...",
                    model, e
                )

        if not succeeded:
            logger.error("All router fallback models failed. Last error: %s", last_error)
            decision["reason"] = f"All router fallback models failed. Last error: {last_error}"

        # Fall back to GENERAL when confidence is too low
        if (
            decision["intent"] in ("RAG", "TOOL", "BOTH")
            and decision["confidence"] < settings.ROUTER_MIN_CONFIDENCE
        ):
            logger.info(
                "Low confidence (%.2f) for intent %s -> GENERAL",
                decision["confidence"],
                decision["intent"],
            )
            decision["intent"] = "GENERAL"
            decision["reason"] = f"Low confidence ({decision['confidence']:.2f}). " + decision.get("reason", "")

        return decision