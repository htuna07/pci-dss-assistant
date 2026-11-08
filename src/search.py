"""Keyword, semantic and hybrid search over chunks, returning requirement IDs."""

from pathlib import Path

from bm25 import BM25Index, tokenize
from config import EMBEDDING_MODEL, EMBEDDING_QUERY_PREFIX, RRF_K
from embeddings import embed_chunks, embed_query, load_model, passage_text

METHODS = ("keyword", "semantic", "hybrid")


class Retriever:
    def __init__(
        self,
        chunks: list[dict],
        methods: tuple[str, ...] = METHODS,
        index_dir: Path | None = None,
        model_name: str = EMBEDDING_MODEL,
    ) -> None:
        self.chunks = chunks
        self.bm25 = BM25Index([tokenize(passage_text(chunk)) for chunk in chunks])
        self.model = None
        if "semantic" in methods or "hybrid" in methods:
            self.model = load_model(model_name)
            self.vectors = embed_chunks(chunks, self.model, model_name, index_dir)

    def keyword_ranking(self, query: str) -> list[int]:
        scores = self.bm25.scores(tokenize(query))
        order = sorted(range(len(self.chunks)), key=lambda i: (-scores[i], i))
        return [i for i in order if scores[i] > 0]

    def semantic_ranking(self, query: str) -> list[int]:
        scores = self.vectors @ embed_query(self.model, query, EMBEDDING_QUERY_PREFIX)
        return sorted(range(len(self.chunks)), key=lambda i: (-scores[i], i))

    def hybrid_ranking(self, query: str) -> list[int]:
        fused: dict[int, float] = {}
        for ranking in (self.keyword_ranking(query), self.semantic_ranking(query)):
            for rank, position in enumerate(ranking, start=1):
                fused[position] = fused.get(position, 0.0) + 1 / (RRF_K + rank)
        return sorted(fused, key=lambda i: (-fused[i], i))

    def search(self, method: str, query: str) -> list[str]:
        """Requirement IDs ordered by their best-ranked chunk."""
        ranking = getattr(self, f"{method}_ranking")(query)
        requirement_ids: list[str] = []
        for position in ranking:
            requirement_id = self.chunks[position]["requirement_id"]
            if requirement_id not in requirement_ids:
                requirement_ids.append(requirement_id)
        return requirement_ids
