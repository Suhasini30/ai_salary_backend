from sentence_transformers import SentenceTransformer


class Embedder:

    def __init__(self, model_name="BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        """
        Load the embedding model only once (lazy loading).
        """
        if self._model is None:
            try:
                self._model = SentenceTransformer(self.model_name)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to load embedding model '{self.model_name}': {e}"
                )

        return self._model

    def embed_chunks(self, chunks):
        """
        Generate embeddings for a list of text chunks.
        """

        if chunks is None:
            raise ValueError("Chunks cannot be None.")

        if not isinstance(chunks, list):
            chunks = [chunks]

        # Remove empty or invalid chunks
        cleaned_chunks = [
            str(chunk).strip()
            for chunk in chunks
            if chunk is not None and str(chunk).strip()
        ]

        if not cleaned_chunks:
            return []

        try:
            embeddings = self.model.encode(
                cleaned_chunks,
                normalize_embeddings=True,
                show_progress_bar=True
            )

            return embeddings

        except Exception as e:
            raise RuntimeError(
                f"Error generating chunk embeddings: {e}"
            )

    def embed_query(self, query):
        """
        Generate embedding for a user query.
        """

        if not isinstance(query, str) or not query.strip():
            raise ValueError(
                "Query must be a non-empty string."
            )

        try:
            embedding = self.model.encode(
                query.strip(),
                normalize_embeddings=True
            )

            return embedding

        except Exception as e:
            raise RuntimeError(
                f"Error generating query embedding: {e}"
            )