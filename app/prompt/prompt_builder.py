from langchain_core.prompts import PromptTemplate


class PromptBuilder:

    def build_prompt(self, query, results):
        context = ""
        for result in results:
            text = result.get("chunk") or result.get("text") or str(result)
            context += text + "\n\n"

        prompt = f"""Context:
{context}

User Question:
{query}
"""
        return prompt

    def build_router_prompt(self, question, rag_results, tool_text, decision):
        intent = decision.get("intent", "GENERAL")

        # GENERAL intent: no RAG/tool context was gathered — just the question.
        if intent == "GENERAL":
            return f"User Question:\n{question}"

        if rag_results:
            rag_context = "\n\n".join(
                result.get("chunk") or result.get("text") or str(result)
                for result in rag_results
                if result
            )
        else:
            rag_context = "No MongoDB dataset context retrieved."

        tool_context = tool_text or "No live job search results."
        confidence_val = decision.get("confidence", 0.0)

        template = PromptTemplate(
            input_variables=[
                "rag_context", "tool_context", "question", "intent", "confidence"
            ],
            template="""Route: {intent} (confidence {confidence})

MongoDB Job Market Data:
{rag_context}

Live Job Search Results:
{tool_context}

User Question:
{question}
""",
        )

        return template.format(
            rag_context=rag_context,
            tool_context=tool_context,
            question=question,
            intent=intent,
            confidence=f"{float(confidence_val):.2f}",
        )