"""What do the extra rewritten queries add? Reads only cached rewrites, never calls a model.

For questions that got several queries, compares the fused result with the first query alone:
an extra query that changes nothing is wasted, one that brings an expected requirement in is a rescue,
one that pushes an expected requirement out is a loss."""

import argparse
from pathlib import Path

from config import (
    DEFAULT_CHUNKS_DIR,
    DEFAULT_EVAL_K,
    DEFAULT_EVAL_QUESTIONS_PATH,
    DEFAULT_INDEX_DIR,
    DEFAULT_REWRITE_MODEL,
    EMBEDDING_MODEL,
    REWRITE_CACHE_NAME,
)
from evaluate import read_jsonl
from rewrite import QueryRewriter
from search import Retriever, fuse_id_rankings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_DIR / "chunks-grouped.jsonl")
    parser.add_argument("--questions", type=Path, default=DEFAULT_EVAL_QUESTIONS_PATH)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--k", type=int, default=8)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    rewriter = QueryRewriter(DEFAULT_REWRITE_MODEL, args.index_dir / REWRITE_CACHE_NAME, cache_only=True)
    retriever = Retriever(read_jsonl(args.chunks), ("hybrid",), args.index_dir, EMBEDDING_MODEL)
    questions = read_jsonl(args.questions)
    counts: dict[int, int] = {}
    unchanged, rescued, lost = [], [], []
    for question in questions:
        queries = rewriter.rewrite(question["question"])
        counts[len(queries)] = counts.get(len(queries), 0) + 1
        if len(queries) < 2:
            continue
        rankings = [retriever.search("hybrid", query) for query in queries]
        first = rankings[0][: args.k]
        fused = fuse_id_rankings(rankings, max(1, args.k // len(rankings)))[: args.k]
        expected = question["expected_requirement_ids"]
        had = [rid for rid in expected if rid in first]
        has = [rid for rid in expected if rid in fused]
        if set(first) == set(fused):
            unchanged.append(question["id"])
        if len(has) > len(had):
            rescued.append(question["id"])
        if len(has) < len(had):
            lost.append(question["id"])
    multi = sum(n for size, n in counts.items() if size > 1)
    print(f"k={args.k} | questions: {len(questions)} | queries per question: "
          + ", ".join(f"{size}: {n}" for size, n in sorted(counts.items())))
    print(f"questions with several queries: {multi}")
    print(f"  extra queries change nothing in the top {args.k}: {len(unchanged)}/{multi}")
    print(f"  extra queries bring an expected requirement in: {len(rescued)} {rescued}")
    print(f"  extra queries push an expected requirement out: {len(lost)} {lost}")


if __name__ == "__main__":
    main()
