import faiss
import numpy as np
import pickle
import os


class VectorStore:

    def __init__(self, dimension=384):
        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)
        self.chunks = []


    def add_embeddings(self, embeddings, chunks):

        embeddings = np.array(embeddings).astype("float32")

        self.index.add(embeddings)
        self.chunks.extend(chunks)


    def search(self, query_embedding, top_k=5):

        query_embedding = np.array(query_embedding).astype("float32").reshape(1, -1)

        scores, indices = self.index.search(query_embedding, top_k)

        results = []

        for score, idx in zip(scores[0], indices[0]):
            results.append({
                "chunk": self.chunks[idx],
                "score": float(score)
            })

        return results


    def save(self, folder="vector_db"):

        os.makedirs(folder, exist_ok=True)

        faiss.write_index(
            self.index,
            os.path.join(folder, "faiss.index")
        )

        with open(
            os.path.join(folder, "chunks.pkl"),
            "wb"
        ) as file:

            pickle.dump(self.chunks, file)


    def load(self, folder="vector_db"):

        self.index = faiss.read_index(
            os.path.join(folder, "faiss.index")
        )

        with open(
            os.path.join(folder, "chunks.pkl"),
            "rb"
        ) as file:

            self.chunks = pickle.load(file)


    def count(self):
        return self.index.ntotal