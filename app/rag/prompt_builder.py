class PromptBuilder:

    def build_prompt(self, query: str, results: list[dict]) -> str:

        context = ""

        for result in results:
            # vector_store.search() projects a "text" field, not "chunk"
            context += result["text"] + "\n\n"

        prompt = f"""
Context:
{context}

User Question:
{query}
"""

        return prompt
