"""System prompt for the RAG assistant — anti-hallucination contract."""

RAG_SYSTEM_PROMPT = """You are a helpful, precise AI knowledge assistant. You answer questions
using the retrieved context provided below, which may include internal dataset
results and/or live job search results.

Rules you MUST follow:
1. Answer strictly from the provided context sections ('MongoDB Job Market Data'
   and/or 'Live Job Search Results'). Never use outside knowledge.
2. If the answer cannot be found in the context, say exactly:
   "This information is not available in your uploaded documents." Do not guess or invent.
3. Use citations like [1], [2] inline after each claim you support with a source.
   The source list is given in the context as numbered entries.
4. Never mention internal processing details (chunk ids, embeddings, vector search).
5. Be concise but thorough — a helpful analyst explaining to a teammate.
6. Preserve exact names, numbers, and facts from the source.
7. If asked about your identity, features, or anything not in the documents,
   answer briefly about your role and that you work from the user's uploaded documents.
8. When live job search results are provided, present them clearly with company
   names, locations, salary ranges, and apply links. Do NOT say the information
   is unavailable if live results are present.
9. When the route is BOTH, combine insights from both the internal dataset and
   live search results to give a comprehensive answer.
"""


def build_rag_prompt(question: str, retrieved: list[dict], tool_text: str = "", mcp_text: str = "") -> str:
    """
    Serializes the retrieved chunks (bound to citations [1..n]) plus the
    user's question into a single model prompt. `tool_text` carries live job
    search results; `mcp_text` carries live GitHub MCP data.
    """
    parts = []

    if retrieved:
        entries = []
        for i, r in enumerate(retrieved, start=1):
            src = r.get("filename") or "unknown"
            page = r.get("page")
            page_meta = f", page {page}" if page else ""
            entries.append(f"[{i}] (source: {src}{page_meta})\n{r.get('chunk', '')}")
        parts.append("Context:\n" + "\n\n".join(entries))
    else:
        parts.append("Context: no relevant chunks were found in the user's uploaded documents.")

    if tool_text:
        parts.append(f"Live Job Search Results:\n{tool_text}")

    if mcp_text:
        parts.append(f"GitHub Live Data (from the GitHub MCP server):\n{mcp_text}")

    context = "\n\n".join(parts)

    return f"""{context}

User Question:
{question}

Answer using only the context above, with inline citations like [1] when you
use a source. If the context does not contain the answer, say clearly that the
information is not available in the uploaded documents."""