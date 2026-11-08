"""Compare keyword, semantic and hybrid search on the evaluation questions."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from config import (
    DEFAULT_CHUNKS_DIR,
    DEFAULT_EVAL_K,
    DEFAULT_EVAL_QUESTIONS_PATH,
    DEFAULT_INDEX_DIR,
    EMBEDDING_MODEL,
)
from search import METHODS, Retriever


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chunks", type=Path, default=DEFAULT_CHUNKS_DIR / "chunks-grouped.jsonl"
    )
    parser.add_argument("--questions", type=Path, default=DEFAULT_EVAL_QUESTIONS_PATH)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--model", default=EMBEDDING_MODEL)
    parser.add_argument("--k", type=int, default=DEFAULT_EVAL_K)
    parser.add_argument(
        "--methods", nargs="+", choices=METHODS, default=list(METHODS)
    )
    parser.add_argument(
        "--misses",
        choices=METHODS,
        help="list the questions this method fails to answer completely",
    )
    return parser


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]


def evaluate(
    retriever: Retriever, questions: list[dict], methods: list[str], k: int
) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {method: [] for method in methods}
    for question in questions:
        expected = question["expected_requirement_ids"]
        for method in methods:
            top = retriever.search(method, question["question"])[:k]
            results[method].append(
                {
                    "question": question,
                    "top": top,
                    "complete": all(rid in top for rid in expected),
                    "any": any(rid in top for rid in expected),
                }
            )
    return results


def format_type_rows(
    results: dict[str, list[dict]], methods: list[str], key: str
) -> list[str]:
    by_type: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: {method: [] for method in methods}
    )
    for method in methods:
        for row in results[method]:
            by_type[row["question"]["type"]][method].append(row[key])
    lines = [f"{'type':<15}{'n':>4}" + "".join(f"{m:>10}" for m in methods)]
    for question_type in sorted(by_type):
        count = len(by_type[question_type][methods[0]])
        lines.append(
            f"{question_type:<15}{count:>4}"
            + "".join(f"{sum(by_type[question_type][m]):>10}" for m in methods)
        )
    return lines


def format_report(results: dict[str, list[dict]], k: int) -> str:
    methods = list(results)
    total = len(next(iter(results.values())))
    lines = [
        f"{'method':<10}{f'all expected in top {k}':>24}{f'at least one in top {k}':>26}"
    ]
    for method in methods:
        rows = results[method]
        lines.append(
            f"{method:<10}"
            f"{sum(r['complete'] for r in rows):>20}/{total}"
            f"{sum(r['any'] for r in rows):>22}/{total}"
        )

    for key, title in (
        ("complete", f"all expected in top {k}"),
        ("any", f"at least one expected in top {k}"),
    ):
        lines += ["", f"{title}, by question type:"]
        lines += format_type_rows(results, methods, key)
    return "\n".join(lines)


def format_misses(results: dict[str, list[dict]], method: str) -> str:
    lines = [f"\nQuestions {method} does not answer completely:"]
    for row in results[method]:
        if row["complete"]:
            continue
        question = row["question"]
        lines.append(
            f"{question['id']} [{question['type']}] {question['question']}\n"
            f"    expected: {', '.join(question['expected_requirement_ids'])}\n"
            f"    got:      {', '.join(row['top']) or '(no match)'}"
        )
    return "\n".join(lines)


def main() -> None:
    args = build_parser().parse_args()
    if args.k < 1:
        raise SystemExit("--k must be at least 1")
    methods = list(dict.fromkeys(args.methods))
    if args.misses and args.misses not in methods:
        raise SystemExit(f"--misses {args.misses} needs it in --methods")

    chunks = read_jsonl(args.chunks)
    questions = read_jsonl(args.questions)
    retriever = Retriever(chunks, tuple(methods), args.index_dir, args.model)
    results = evaluate(retriever, questions, methods, args.k)

    print(f"chunks: {args.chunks.name} | k={args.k} | questions: {len(questions)}")
    print(format_report(results, args.k))
    if args.misses:
        print(format_misses(results, args.misses))


if __name__ == "__main__":
    main()
