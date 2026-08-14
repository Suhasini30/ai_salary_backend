import json
import logging
import re

from litellm import completion

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
    """Classifies a user question into RAG / TOOL / BOTH / GENERAL."""

    def classify(self, question):
        decision = {
            "intent": "GENERAL",
            "confidence": 0.0,
            "reason": "Router output was unparseable",
        }

        try:
            response = completion(
                model=settings.ROUTER_MODEL,
                messages=[
                    {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                    {"role": "user", "content": ROUTER_USER_PROMPT.format(question=question)},
                ],
                temperature=0,
                max_tokens=120,
            )

            raw = response.choices[0].message.content or ""
            payload = json.loads(_extract_json(raw))

            intent = str(payload.get("intent") or "").upper()
            confidence = float(payload.get("confidence") or 0.0)

            if intent not in VALID_INTENTS:
                intent = "GENERAL"

            decision = {
                "intent": intent,
                "confidence": max(0.0, min(1.0, confidence)),
                "reason": str(payload.get("reason") or ""),
            }

        except Exception as e:
            logger.warning("Router failed (%s), falling back to GENERAL.", e)

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
            decision["reason"] = f"Low confidence ({decision['confidence']:.2f}). " + decision["reason"]

        return decision