from langchain_core.prompts import PromptTemplate


class PromptBuilder:

    def build_prompt(self, query, results):
        context = ""

        for result in results:
            context += result["chunk"] + "\n\n"

        prompt = f"""
Context:
{context}

User Question:
{query}
"""

        return prompt

    def build_router_prompt(self, question, rag_results, tool_text, decision):
        if rag_results:
            rag_context = "\n".join(
                result["chunk"] for result in rag_results
            )
        else:
            rag_context = "No internal dataset context retrieved."

        tool_context = tool_text or "No live job search results."

        template = PromptTemplate(
            input_variables=[
                "rag_context", "tool_context", "question", "intent", "confidence"
            ],
            template="""Route: {intent} (confidence {confidence})

Internal Job Data:
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
            intent=decision["intent"],
            confidence=f"{float(decision['confidence']):.2f}",
        )