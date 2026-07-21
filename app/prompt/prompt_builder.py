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