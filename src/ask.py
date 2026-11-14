"""Answer a question from the most relevant PCI DSS requirements, with citations."""

import argparse
from pathlib import Path

from config import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_ANSWER_TOP_K,
    DEFAULT_CHUNKS_DIR,
    DEFAULT_EVAL_QUESTIONS_PATH,
    DEFAULT_INDEX_DIR,
    EMBEDDING_MODEL,
    PROJECT_ROOT,
)
from errors import GenerationError
from generate import SYSTEM_PROMPT, check_answer, run_claude_cli
from pipeline import Assistant, read_jsonl

UNANSWERABLE_PATH = PROJECT_ROOT / "eval" / "unanswerable.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?")
    parser.add_argument(
        "--from-eval",
        nargs="+",
        metavar="ID",
        help="ask evaluation questions by id (for example q03 u01)",
    )
    parser.add_argument(
        "--chunks", type=Path, default=DEFAULT_CHUNKS_DIR / "chunks-grouped.jsonl"
    )
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    parser.add_argument("--model", default=DEFAULT_ANSWER_MODEL)
    parser.add_argument("--k", type=int, default=DEFAULT_ANSWER_TOP_K)
    parser.add_argument(
        "--no-rewrite",
        action="store_true",
        help="search with the question as typed instead of model-rewritten queries",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the prompt that would be sent instead of calling the model "
        "(rewrites are only reused from the cache, never requested)",
    )
    parser.add_argument(
        "--use-answer",
        metavar="TEXT",
        help="skip the model and only check this answer text against the retrieved requirements",
    )
    return parser


def select_questions(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.from_eval:
        known = {
            row["id"]: row
            for row in read_jsonl(DEFAULT_EVAL_QUESTIONS_PATH) + read_jsonl(UNANSWERABLE_PATH)
        }
        unknown = [qid for qid in args.from_eval if qid not in known]
        if unknown:
            raise SystemExit(f"Unknown evaluation question ids: {', '.join(unknown)}")
        return [(qid, known[qid]["question"]) for qid in args.from_eval]
    if args.question:
        return [("", args.question)]
    raise SystemExit("Give a question or --from-eval ids")


def format_check(check: dict) -> str:
    if check["not_found"]:
        return "reply: could not find an answer in the retrieved requirements"
    parts = [f"cited: {', '.join(check['cited']) or '(none)'}"]
    if check["outside_sources"]:
        parts.append(f"WARNING cited but not retrieved: {', '.join(check['outside_sources'])}")
    if not check["cited"]:
        parts.append("WARNING no citations")
    return " | ".join(parts)


def main() -> None:
    args = build_parser().parse_args()
    if args.k < 1:
        raise SystemExit("--k must be at least 1")
    questions = select_questions(args)

    assistant = Assistant.from_files(
        args.chunks,
        args.index_dir,
        args.embedding_model,
        model=args.model,
        k=args.k,
        rewrite=not args.no_rewrite,
        offline=args.dry_run or args.use_answer is not None,
    )

    for label, question in questions:
        prepared = assistant.prepare(question)
        retrieved = prepared.retrieved

        print(f"\n=== {label + ' ' if label else ''}{question}")
        if assistant.rewriter:
            print(f"search queries: {' | '.join(prepared.queries)}")
        print(f"retrieved: {', '.join(retrieved)}")

        if args.dry_run:
            print(
                f"\n--- system prompt ---\n{SYSTEM_PROMPT}"
                f"\n\n--- user prompt ---\n{prepared.user_prompt}"
            )
            continue

        if args.use_answer is not None:
            answer = args.use_answer
        else:
            try:
                answer = run_claude_cli(SYSTEM_PROMPT, prepared.user_prompt, args.model)
            except GenerationError as error:
                raise SystemExit(f"Generation failed: {error}") from error

        print(f"\n{answer}\n")
        print(f"check: {format_check(check_answer(answer, retrieved))}")


if __name__ == "__main__":
    main()
