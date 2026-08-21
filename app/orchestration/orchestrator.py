import logging

from app.core.config import settings
from app.models.schemas import ChatEventType
from app.prompt.prompt_builder import PromptBuilder
from app.prompt.rag_prompt import RAG_SYSTEM_PROMPT
from app.prompt.system_prompt import GENERAL_SYSTEM_PROMPT, SYSTEM_PROMPT
from app.services.llm_router import LLMRouter
from app.services.llm import LLMService
from app.tools.jsearch import JSearchTool

logger = logging.getLogger(__name__)


def _select_system_prompt(intent: str) -> str:
    """Picks the system prompt that matches the routed intent.

    RAG   → strict citations, anti-hallucination contract.
    TOOL/BOTH → market assistant persona (live listings + apply links).
    MCP/GENERAL → friendly general assistant that may answer from its own knowledge.
    """
    if intent == "RAG":
        return RAG_SYSTEM_PROMPT
    if intent in ("TOOL", "BOTH"):
        return SYSTEM_PROMPT
    return GENERAL_SYSTEM_PROMPT


def _clean_sources(retrieved: list[dict]) -> list[dict]:
    """Normalises retrieved chunks into the shape the frontend renders."""
    cleaned = []
    for r in retrieved:
        cleaned.append(
            {
                "filename": r.get("filename") or "unknown",
                "page": r.get("page"),
                "chunk_index": r.get("chunk_index"),
                "document_id": r.get("document_id"),
                "score": r.get("score", 0.0),
                "chunk_content": (r.get("chunk") or r.get("text") or "")[:600],
            }
        )
    return cleaned


class SalesOrchestrator:
    def __init__(self, retriever, llm_service=None):
        self.router = LLMRouter()
        self.retriever = retriever
        self.jsearch_tool = JSearchTool()
        self.llm_service = llm_service or LLMService()
        self.prompt_builder = PromptBuilder()

    async def answer(self, question, user=None):
        """
        Async generator yielding SSE event dicts:
          meta → sources → token* → done

        Per workflow.md:
          1. classify intent (RAG / MCP / TOOL / BOTH / GENERAL),
          2. retrieve RAG context when RAG/BOTH (scoped to the user),
          3. call JSearch when TOOL/BOTH,
          4. call the GitHub MCP tools when MCP,
          5. build the prompt,
          6. stream the LLM response chunk by chunk.
        """
        decision = await self.router.classify(question)
        intent = decision.get("intent", "GENERAL")

        logger.info(
            "Route => intent=%s confidence=%.2f reason=%s",
            intent, decision.get("confidence", 0.0), decision.get("reason", ""),
        )

        yield {
            "event": ChatEventType.META.value,
            "data": {
                "intent": intent,
                "confidence": decision.get("confidence", 0.0),
            },
        }

        rag_results = []
        tool_text = ""
        mcp_text = ""

        if intent in ("RAG", "BOTH"):
            try:
                if self.retriever:
                    if user is not None and hasattr(self.retriever, "retrieve_for_user"):
                        rag_results = await self.retriever.retrieve_for_user(question, user.id)
                    else:
                        rag_results = await self.retriever.retrieve(question)
            except Exception as e:
                logger.error("MongoDB Atlas retrieval failed in orchestrator: %s", e, exc_info=True)

        if intent in ("TOOL", "BOTH"):
            try:
                tool_text, ok = await self.jsearch_tool.search_results(question)
                if ok:
                    logger.info("JSearch tool returned live job listings.")
            except Exception as e:
                logger.error("JSearch tool failed in orchestrator: %s", e, exc_info=True)

        if intent == "MCP":
            try:
                from app.mcp.github_tools import run_github_tools
                from app.repos import profiles_repo

                github_token = None
                if user is not None:
                    user_id = str(user.id) if hasattr(user, "id") else str(user.get("id")) if isinstance(user, dict) else None
                    if user_id:
                        oauth_info = await profiles_repo.get_github_oauth(user_id)
                        if oauth_info:
                            github_token = oauth_info.get("access_token")

                mcp_text = await run_github_tools(question, github_token=github_token)
                if mcp_text:
                    logger.info("GitHub MCP returned live data (%d chars).", len(mcp_text))
            except Exception as exc:
                logger.warning("GitHub MCP tool run failed: %s", exc)

        sources = _clean_sources(rag_results)
        yield {
            "event": ChatEventType.SOURCES.value,
            "data": {
                "sources": sources,
                "intent": intent,
                "tool_text": tool_text,
                "mcp_text": mcp_text,
            },
        }

        prompt = self.prompt_builder.build_router_prompt(
            question, rag_results, tool_text, decision, mcp_text=mcp_text
        )
        logger.info("Final LLM prompt built (len=%d chars).", len(prompt))

        system_prompt = _select_system_prompt(intent)
        async for chunk in self.llm_service.chat(prompt, system_prompt=system_prompt):
            yield {"event": ChatEventType.TOKEN.value, "data": {"content": chunk}}

        yield {"event": ChatEventType.DONE.value, "data": {"intent": intent}}