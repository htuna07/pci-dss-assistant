"""Keyword, semantic and hybrid search over chunks, returning requirement IDs."""

import re
from pathlib import Path

from bm25 import BM25Index, tokenize
from config import EMBEDDING_MODEL, EMBEDDING_QUERY_PREFIX, RRF_K
from embeddings import embed_chunks, embed_query, load_model, passage_text
from rewrite import QueryRewriter

METHODS = ("keyword", "semantic", "hybrid", "hybrid_id")
REWRITE_METHOD = "hybrid_rewrite"
ALL_METHODS = (*METHODS, REWRITE_METHOD)
SEMANTIC_METHODS = ("semantic", "hybrid", "hybrid_id", REWRITE_METHOD)
DOTTED_ID = re.compile(r"\d+(?:\.\d+)+")
PRINCIPAL_ID = re.compile(r"\brequirements?\s+(\d+)\b", re.IGNORECASE)


def fuse_id_rankings(rankings: list[list[str]]) -> list[str]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, requirement_id in enumerate(ranking, start=1):
            fused[requirement_id] = fused.get(requirement_id, 0.0) + 1 / (RRF_K + rank)
    return sorted(fused, key=lambda requirement_id: -fused[requirement_id])


class Retriever:
    def __init__(
        self,
        chunks: list[dict],
        methods: tuple[str, ...] = METHODS,
        index_dir: Path | None = None,
        model_name: str = EMBEDDING_MODEL,
        rewriter: QueryRewriter | None = None,
    ) -> None:
        if REWRITE_METHOD in methods and rewriter is None:
            raise ValueError(f"{REWRITE_METHOD} needs a rewriter")
        self.rewriter = rewriter
        self.chunks = chunks
        self.known_ids = {chunk["requirement_id"] for chunk in chunks}
        self.bm25 = BM25Index([tokenize(passage_text(chunk)) for chunk in chunks])
        self.model = None
        if any(method in SEMANTIC_METHODS for method in methods):
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

    def mentioned_ids(self, query: str) -> list[str]:
        """Only IDs that exist, so "PCI DSS v4.0.1" is not mistaken for a requirement."""
        found = DOTTED_ID.findall(query) + PRINCIPAL_ID.findall(query)
        return list(dict.fromkeys(rid for rid in found if rid in self.known_ids))

    def search(self, method: str, query: str) -> list[str]:
        """Requirement IDs ordered by their best-ranked chunk."""
        if method == "hybrid_id":
            mentioned = self.mentioned_ids(query)
            rest = self.search("hybrid", query)
            return mentioned + [rid for rid in rest if rid not in mentioned]
        if method == REWRITE_METHOD:
            mentioned = self.mentioned_ids(query)
            rankings = [self.search("hybrid", rewritten) for rewritten in self.rewriter.rewrite(query)]
            return mentioned + [rid for rid in fuse_id_rankings(rankings) if rid not in mentioned]
        ranking = getattr(self, f"{method}_ranking")(query)
        requirement_ids: list[str] = []
        for position in ranking:
            requirement_id = self.chunks[position]["requirement_id"]
            if requirement_id not in requirement_ids:
                requirement_ids.append(requirement_id)
        return requirement_ids
