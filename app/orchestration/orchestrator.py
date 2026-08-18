import logging

from app.prompt.prompt_builder import PromptBuilder
from app.routers.llm_router import LLMRouter
from app.services.llm import LLMService
from app.tools.jsearch import JSearchTool

logger = logging.getLogger(__name__)


class SalesOrchestrator:
    def __init__(self, retriever, llm_service=None):
        self.router = LLMRouter()
        self.retriever = retriever
        self.jsearch_tool = JSearchTool()
        self.llm_service = llm_service or LLMService()
        self.prompt_builder = PromptBuilder()

    async def answer(self, question, model):
        """
        Async generator: classifies intent, retrieves RAG context (awaited,
        no asyncio.run — reuses the running event loop so the long-lived
        Motor client never gets orphaned), calls tools if needed, builds the
        prompt, then streams the LLM response chunk by chunk.
        """
        decision = await self.router.classify(question)
        intent = decision.get("intent", "GENERAL")

        logger.info(
            "Route => intent=%s confidence=%.2f reason=%s",
            intent, decision.get("confidence", 0.0), decision.get("reason", ""),
        )

        rag_results = []
        tool_text = ""

        if intent in ("RAG", "BOTH"):
            try:
                if self.retriever:
                    rag_results = await self.retriever.retrieve(question)
            except Exception as e:
                logger.error("MongoDB Atlas retrieval failed in orchestrator: %s", e, exc_info=True)

        if intent in ("TOOL", "BOTH"):
            try:
                tool_text, ok = self.jsearch_tool.search_results(question)
                if ok:
                    logger.info("JSearch tool returned live job listings.")
            except Exception as e:
                logger.error("JSearch tool failed in orchestrator: %s", e, exc_info=True)

        prompt = self.prompt_builder.build_router_prompt(
            question, rag_results, tool_text, decision
        )
        logger.info("Final LLM prompt built (len=%d chars).", len(prompt))

        for chunk in self.llm_service.chat(prompt, model):
            yield chunk