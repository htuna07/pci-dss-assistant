"""Answer a question from the most relevant PCI DSS requirements, with citations."""

import argparse
import json
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
from generate import (
    SYSTEM_PROMPT,
    build_sources,
    build_user_prompt,
    check_answer,
    run_claude_cli,
)
from search import Retriever

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
        "--dry-run",
        action="store_true",
        help="print the prompt that would be sent instead of calling the model",
    )
    parser.add_argument(
        "--use-answer",
        metavar="TEXT",
        help="skip the model and only check this answer text against the retrieved requirements",
    )
    return parser


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


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

    chunks = read_jsonl(args.chunks)
    retriever = Retriever(chunks, ("hybrid_id",), args.index_dir, args.embedding_model)

    for label, question in questions:
        retrieved = retriever.search("hybrid_id", question)[: args.k]
        sources = build_sources(chunks, retrieved)
        user_prompt = build_user_prompt(question, sources)

        print(f"\n=== {label + ' ' if label else ''}{question}")
        print(f"retrieved: {', '.join(retrieved)}")

        if args.dry_run:
            print(f"\n--- system prompt ---\n{SYSTEM_PROMPT}\n\n--- user prompt ---\n{user_prompt}")
            continue

        if args.use_answer is not None:
            answer = args.use_answer
        else:
            try:
                answer = run_claude_cli(SYSTEM_PROMPT, user_prompt, args.model)
            except GenerationError as error:
                raise SystemExit(f"Generation failed: {error}") from error

        print(f"\n{answer}\n")
        print(f"check: {format_check(check_answer(answer, retrieved))}")


if __name__ == "__main__":
    main()
