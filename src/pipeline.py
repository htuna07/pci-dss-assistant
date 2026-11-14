"""One question in, one cited answer out; shared by the command line and the web server."""

from dataclasses import dataclass
from pathlib import Path

from config import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_REWRITE_MODEL,
    REWRITE_CACHE_NAME,
)
from generate import (
    SYSTEM_PROMPT,
    build_user_prompt,
    check_answer,
    format_sources,
    group_sources,
    run_claude_cli,
)
from jsonl_io import read_jsonl
from rewrite import QueryRewriter
from search import REWRITE_METHOD, Retriever


@dataclass(frozen=True)
class Prepared:
    queries: list[str]
    retrieved: list[str]
    sources: list[dict]
    user_prompt: str


@dataclass(frozen=True)
class Answer:
    prepared: Prepared
    text: str
    check: dict


class Assistant:
    def __init__(
        self,
        chunks: list[dict],
        retriever: Retriever,
        method: str,
        rewriter: QueryRewriter | None,
        model: str,
        k: int,
    ) -> None:
        self.chunks = chunks
        self.retriever = retriever
        self.method = method
        self.rewriter = rewriter
        self.model = model
        self.k = k

    @classmethod
    def from_files(
        cls,
        chunks_path: Path,
        index_dir: Path,
        embedding_model: str,
        model: str = DEFAULT_ANSWER_MODEL,
        k: int = 8,
        rewrite: bool = True,
        offline: bool = False,
        persist_rewrites: bool = True,
    ) -> "Assistant":
        chunks = read_jsonl(chunks_path)
        rewriter = None
        method = "hybrid_id"
        if rewrite:
            cache_path = index_dir / REWRITE_CACHE_NAME if persist_rewrites else None
            rewriter = QueryRewriter(DEFAULT_REWRITE_MODEL, cache_path, cache_only=offline)
            method = REWRITE_METHOD
        retriever = Retriever(chunks, (method,), index_dir, embedding_model, rewriter)
        return cls(chunks, retriever, method, rewriter, model, k)

    def prepare(self, question: str) -> Prepared:
        retrieved = self.retriever.search(self.method, question)[: self.k]
        queries = self.rewriter.rewrite(question) if self.rewriter else []
        sources = group_sources(self.chunks, retrieved)
        return Prepared(queries, retrieved, sources, build_user_prompt(question, format_sources(sources)))

    def answer(self, question: str) -> Answer:
        """Raises GenerationError when the model call fails."""
        prepared = self.prepare(question)
        text = run_claude_cli(SYSTEM_PROMPT, prepared.user_prompt, self.model)
        return Answer(prepared, text, check_answer(text, prepared.retrieved))
