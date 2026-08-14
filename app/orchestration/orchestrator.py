import logging

from app.prompt.prompt_builder import PromptBuilder
from app.routers.llm_router import LLMRouter
from app.services.llm import LLMService
from app.tools.jsearch import JSearchTool

logger = logging.getLogger(__name__)


class SalesOrchestrator:
    """
    Routes each user question through the LLM router and combines the
    matching data sources (internal RAG dataset and/or live JSearch tool)
    before streaming the final LLM answer.
    """

    def __init__(self, retriever, llm_service=None):
        self.router = LLMRouter()
        self.retriever = retriever
        self.jsearch_tool = JSearchTool()
        self.llm_service = llm_service or LLMService()
        self.prompt_builder = PromptBuilder()

    def answer(self, question, model):
        decision = self.router.classify(question)
        intent = decision["intent"]

        logger.info(
            "Route => intent=%s confidence=%.2f reason=%s",
            intent, decision["confidence"], decision["reason"],
        )

        rag_results = []
        tool_text = ""

        if intent in ("RAG", "BOTH"):
            rag_results = self.retriever.retrieve(question)

        if intent in ("TOOL", "BOTH"):
            tool_text, tool_ok = self.jsearch_tool.search_results(question)
            if not tool_ok:
                logger.warning("JSearch unavailable for job query (intent=%s).", intent)

        prompt = self.prompt_builder.build_router_prompt(
            question=question,
            rag_results=rag_results,
            tool_text=tool_text,
            decision=decision,
        )

        yield from self.llm_service.chat(prompt, model)