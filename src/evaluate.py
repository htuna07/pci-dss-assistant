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
    DEFAULT_REWRITE_MODEL,
    EMBEDDING_MODEL,
    REWRITE_CACHE_NAME,
)
from rewrite import QueryRewriter
from search import ALL_METHODS, METHODS, REWRITE_METHOD, Retriever


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
        "--methods",
        nargs="+",
        choices=ALL_METHODS,
        default=list(METHODS),
        help=f"{REWRITE_METHOD} calls a model once per question (rewrites are cached)",
    )
    parser.add_argument(
        "--misses",
        choices=ALL_METHODS,
        help="list the questions this method fails to answer completely",
    )
    parser.add_argument(
        "--save", type=Path, help="write the per-question results to this JSON file"
    )
    parser.add_argument(
        "--compare",
        type=Path,
        help="compare with results saved earlier: which questions got fixed or broke",
    )
    return parser


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        message = f"File not found: {path}"
        if path.parent.name == "chunks":
            message += "\nBuild the chunks first with: python src/build_chunks.py"
        raise SystemExit(message)
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


def column_width(method: str) -> int:
    return max(10, len(method) + 1)


def format_type_rows(
    results: dict[str, list[dict]], methods: list[str], key: str
) -> list[str]:
    by_type: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: {method: [] for method in methods}
    )
    for method in methods:
        for row in results[method]:
            by_type[row["question"]["type"]][method].append(row[key])
    lines = [f"{'type':<15}{'n':>4}" + "".join(f"{m:>{column_width(m)}}" for m in methods)]
    for question_type in sorted(by_type):
        count = len(by_type[question_type][methods[0]])
        lines.append(
            f"{question_type:<15}{count:>4}"
            + "".join(f"{sum(by_type[question_type][m]):>{column_width(m)}}" for m in methods)
        )
    return lines


def format_report(results: dict[str, list[dict]], k: int) -> str:
    methods = list(results)
    total = len(next(iter(results.values())))
    name_width = max(10, *(len(method) + 1 for method in methods))
    lines = [
        f"{'method':<{name_width}}{f'all expected in top {k}':>24}{f'at least one in top {k}':>26}"
    ]
    for method in methods:
        rows = results[method]
        lines.append(
            f"{method:<{name_width}}"
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


def snapshot(results: dict[str, list[dict]], k: int, chunks_name: str) -> dict:
    # Only IDs and flags, never chunk text, so a snapshot holds nothing from the standard.
    first = next(iter(results.values()))
    return {
        "k": k,
        "chunks": chunks_name,
        "question_ids": [row["question"]["id"] for row in first],
        "methods": {
            method: {
                row["question"]["id"]: {
                    "top": row["top"],
                    "complete": row["complete"],
                    "any": row["any"],
                }
                for row in rows
            }
            for method, rows in results.items()
        },
    }


def load_snapshot(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path} is not a saved evaluation: {error}") from error


def format_comparison(baseline: dict, current: dict) -> str:
    # Different k or questions would make every difference meaningless, so refuse.
    for key in ("k", "chunks", "question_ids"):
        if baseline.get(key) != current[key]:
            raise SystemExit(
                f"Cannot compare: the saved run differs in '{key}' "
                f"(saved: {baseline.get(key)!r}, now: {current[key]!r})"
            )
    shared = [method for method in current["methods"] if method in baseline["methods"]]
    if not shared:
        raise SystemExit(
            "Cannot compare: no method in common "
            f"(saved: {', '.join(baseline['methods'])}; now: {', '.join(current['methods'])})"
        )

    total = len(current["question_ids"])
    lines = []
    for method in shared:
        before, after = baseline["methods"][method], current["methods"][method]
        fixed = [q for q in current["question_ids"] if after[q]["complete"] and not before[q]["complete"]]
        broken = [q for q in current["question_ids"] if before[q]["complete"] and not after[q]["complete"]]
        any_before = sum(before[q]["any"] for q in current["question_ids"])
        any_after = sum(after[q]["any"] for q in current["question_ids"])
        complete_before = sum(before[q]["complete"] for q in current["question_ids"])
        complete_after = sum(after[q]["complete"] for q in current["question_ids"])
        reordered = sum(
            before[q]["top"] != after[q]["top"] for q in current["question_ids"]
        )
        lines += [
            f"{method}: all expected {complete_before}/{total} -> {complete_after}/{total}, "
            f"at least one {any_before}/{total} -> {any_after}/{total}",
            f"  fixed:  {', '.join(fixed) or '-'}",
            f"  broken: {', '.join(broken) or '-'}",
            f"  questions whose top list changed at all: {reordered}",
        ]
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
    rewriter = None
    if REWRITE_METHOD in methods:
        rewriter = QueryRewriter(DEFAULT_REWRITE_MODEL, args.index_dir / REWRITE_CACHE_NAME)
        rewriter.rewrite_many([question["question"] for question in questions])
    retriever = Retriever(chunks, tuple(methods), args.index_dir, args.model, rewriter)
    results = evaluate(retriever, questions, methods, args.k)

    print(f"chunks: {args.chunks.name} | k={args.k} | questions: {len(questions)}")
    print(format_report(results, args.k))
    if args.misses:
        print(format_misses(results, args.misses))

    current = snapshot(results, args.k, args.chunks.name)
    if args.compare:
        print("\nCompared with " + str(args.compare) + ":")
        print(format_comparison(load_snapshot(args.compare), current))
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(current, indent=1) + "\n", encoding="utf-8")
        print(f"\nSaved: {args.save}")


if __name__ == "__main__":
    main()
