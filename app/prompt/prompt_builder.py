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

    def build_router_prompt(self, question, rag_results, tool_text, decision, mcp_text=""):
        intent = decision.get("intent", "GENERAL")

        if rag_results:
            rag_context = "\n\n".join(
                result.get("chunk") or result.get("text") or str(result)
                for result in rag_results
                if result
            )
        else:
            rag_context = "No MongoDB dataset context retrieved."

        tool_context = tool_text or "No live job search results."
        mcp_context = mcp_text or "No active MCP tools loaded."
        confidence_val = decision.get("confidence", 0.0)

        # MCP intent: answer from live GitHub data.
        if intent == "MCP":
            return f"""You are a helpful assistant with live access to the user's GitHub data via the Model Context Protocol (MCP).

GitHub Live Data:
{mcp_context}

User Question:
{question}

Rules:
- Answer using the GitHub Live Data above. When listing repositories include
  names, links, languages, and star counts.
- If the data is empty, say clearly that GitHub data could not be fetched.
- Never invent repositories, stars, or URLs that are not in the data.
"""

        # GENERAL intent with MCP context
        if intent == "GENERAL":
            return f"""You are a helpful assistant with live tool access via the GitHub Model Context Protocol (MCP).

GitHub Live Data:
{mcp_context}

User Question:
{question}

Rules:
- If GitHub Live Data is present and relevant, answer using it directly and
  accurately (e.g. list the repositories with names, links, languages, stars).
- If the data is empty or irrelevant to the question, answer normally from your
  own knowledge.
- Never claim to access GitHub when the data is absent.
"""

        template = PromptTemplate(
            input_variables=[
                "rag_context", "tool_context", "mcp_context", "question", "intent", "confidence"
            ],
            template="""Route: {intent} (confidence {confidence})

MongoDB Job Market Data:
{rag_context}

Live Job Search Results:
{tool_context}

Model Context Protocol (MCP) Integration:
{mcp_context}

User Question:
{question}
""",
        )

        return template.format(
            rag_context=rag_context,
            tool_context=tool_context,
            mcp_context=mcp_context,
            question=question,
            intent=intent,
            confidence=f"{float(confidence_val):.2f}",
        )