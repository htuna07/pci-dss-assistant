"""Answer-level evaluation without a judge: does the assistant refuse exactly when it should,
and does it cite the requirements it should?"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from config import (
    NOT_FOUND_REPLY,
    DEFAULT_ANSWER_MODEL,
    DEFAULT_ANSWER_TOP_K,
    DEFAULT_CHUNKS_DIR,
    DEFAULT_EVAL_QUESTIONS_PATH,
    DEFAULT_INDEX_DIR,
    EMBEDDING_MODEL,
    PROJECT_ROOT,
)
from errors import GenerationError
from evaluate import headline_hit
from generate import SYSTEM_PROMPT, check_answer, run_claude_cli
from jsonl_io import read_jsonl
from pipeline import Assistant

UNANSWERABLE_PATH = PROJECT_ROOT / "eval" / "unanswerable.jsonl"
PARTIAL_PATH = PROJECT_ROOT / "eval" / "partial.jsonl"
ANSWER_CACHE_NAME = "answers.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chunks", type=Path, default=DEFAULT_CHUNKS_DIR / "chunks-grouped.jsonl"
    )
    parser.add_argument("--questions", type=Path, default=DEFAULT_EVAL_QUESTIONS_PATH)
    parser.add_argument("--unanswerable", type=Path, default=UNANSWERABLE_PATH)
    parser.add_argument("--partial", type=Path, default=PARTIAL_PATH)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    parser.add_argument("--model", default=DEFAULT_ANSWER_MODEL)
    parser.add_argument("--k", type=int, default=DEFAULT_ANSWER_TOP_K)
    parser.add_argument(
        "--ids", nargs="+", metavar="ID", help="only these question ids (for example q24 u01)"
    )
    parser.add_argument(
        "--cached-only",
        action="store_true",
        help="never call a model: use cached answers and rewrites, report the rest as not run",
    )
    return parser


class AnswerCache:
    """Answers keyed by a hash of model, rules and the full prompt, so a change to the prompt or
    to the retrieved sources never reuses a stale answer. Answers may quote the standard, so the
    file belongs under the gitignored data/ folder."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, str] = {}
        if path.is_file():
            self.entries = json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def key(model: str, user_prompt: str) -> str:
        digest = hashlib.sha256()
        for part in (model, SYSTEM_PROMPT, user_prompt):
            digest.update(part.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def get(self, key: str) -> str | None:
        return self.entries.get(key)

    def put(self, key: str, answer: str) -> None:
        self.entries[key] = answer
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Saved after every answer so an interrupted run keeps what it paid for.
        self.path.write_text(json.dumps(self.entries, indent=1) + "\n", encoding="utf-8")


def load_cases(args: argparse.Namespace) -> list[dict]:
    cases = [
        {**row, "answerable": True, "expected": row["expected_requirement_ids"]}
        for row in read_jsonl(args.questions)
    ]
    # Partly answerable: the standard answers one half, so the right reply cites that half and
    # says plainly that the other half is not covered; refusing everything is the failure.
    cases += [
        {**row, "answerable": True, "partial": True, "type": "partial",
         "expected": row["expected_requirement_ids"]}
        for row in read_jsonl(args.partial)
    ]
    cases += [
        {**row, "answerable": False, "expected": [], "type": "unanswerable"}
        for row in read_jsonl(args.unanswerable)
    ]
    if args.ids:
        unknown = [qid for qid in args.ids if qid not in {case["id"] for case in cases}]
        if unknown:
            raise SystemExit(f"Unknown question ids: {', '.join(unknown)}")
        cases = [case for case in cases if case["id"] in args.ids]
    return cases


def run_case(
    assistant: Assistant, cache: AnswerCache, case: dict, cached_only: bool, introductions: set[str]
) -> dict:
    prepared = assistant.prepare(case["question"])
    row = {
        "case": case,
        "retrieved": prepared.retrieved,
        "status": "ok",
        "check": None,
        # The answer rules call introductions background, never a rule to cite, so a question whose
        # expected list holds only introductions cannot be scored by citations.
        "intro_only": bool(case["expected"]) and all(rid in introductions for rid in case["expected"]),
    }
    key = AnswerCache.key(assistant.model, prepared.user_prompt)
    text = cache.get(key)
    if text is None:
        if cached_only:
            row["status"] = "not run"
            return row
        try:
            text = run_claude_cli(SYSTEM_PROMPT, prepared.user_prompt, assistant.model)
        except GenerationError as error:
            row["status"] = f"error: {error}"
            return row
        cache.put(key, text)
    row["check"] = check_answer(text, prepared.retrieved)
    # The rules say to reply exactly with the fixed sentence; a refusal that goes on writing is a
    # different behavior (often an honest "the sources only say this much") worth reading.
    row["refusal_only"] = text.strip() == NOT_FOUND_REPLY
    return row


def expected_cited(row: dict) -> tuple[bool, bool]:
    """(all expected cited, at least one expected cited)."""
    expected = row["case"]["expected"]
    cited = row["check"]["cited"]
    return all(rid in cited for rid in expected), any(rid in cited for rid in expected)


def format_refusals(rows: list[dict]) -> list[str]:
    done = [row for row in rows if row["check"] is not None]
    answerable = [
        row for row in done if row["case"]["answerable"] and not row["case"].get("partial")
    ]
    unanswerable = [row for row in done if not row["case"]["answerable"]]
    refused = lambda group: sum(row["check"]["not_found"] for row in group)  # noqa: E731

    lines = [
        f"{'':<24}{'answered':>10}{'refused':>10}",
        f"{f'answerable ({len(answerable)})':<24}{len(answerable) - refused(answerable):>10}{refused(answerable):>10}   <- refused = false refusal",
        f"{f'unanswerable ({len(unanswerable)})':<24}{len(unanswerable) - refused(unanswerable):>10}{refused(unanswerable):>10}   <- answered = invented answer risk",
    ]
    for row in done:
        if row["check"]["not_found"] and not row["refusal_only"] and not row["case"].get("partial"):
            lines.append(f"  refused, then kept writing: {row['case']['id']}")
    for row in answerable:
        if row["check"]["not_found"]:
            in_sources = any(rid in row["retrieved"] for rid in row["case"]["expected"])
            lines.append(
                f"  false refusal {row['case']['id']}: an expected requirement "
                + ("was" if in_sources else "was NOT")
                + " among the sources "
                + ("(model or prompt problem)" if in_sources else "(retrieval problem)")
            )
    for row in unanswerable:
        if not row["check"]["not_found"]:
            lines.append(f"  answered although unanswerable: {row['case']['id']} {row['case']['question']}")
    return lines


def format_partial(rows: list[dict]) -> list[str]:
    partial = [row for row in rows if row["check"] is not None and row["case"].get("partial")]
    lines = [f"partly answerable questions: {len(partial)}"]
    for row in partial:
        check = row["check"]
        if check["not_found"] and row["refusal_only"]:
            verdict = "refused everything (useful part withheld)"
        elif check["not_found"]:
            verdict = "refusal sentence, then kept writing (mixed signal)"
        elif expected_cited(row)[0]:
            verdict = "answered, expected cited"
        else:
            verdict = "answered, expected NOT all cited"
        lines.append(f"  {row['case']['id']}: {verdict}")
    return lines


def format_citations(rows: list[dict]) -> list[str]:
    answered = [
        row for row in rows
        if row["check"] is not None and row["case"]["answerable"]
        and not row["case"].get("partial") and not row["check"]["not_found"]
    ]
    unscorable = [row for row in answered if row["intro_only"]]
    answered = [row for row in answered if not row["intro_only"]]
    no_citation = [row for row in answered if not row["check"]["cited"]]
    invented = [row for row in answered if row["check"]["outside_sources"]]
    hits = sum(
        headline_hit(row["case"]["type"], *expected_cited(row)) for row in answered
    )
    lines = [
        f"answered answerable questions: {len(answered)}",
        f"  without any citation:            {len(no_citation)}",
        f"  citing a requirement that was not among the sources: {len(invented)}",
        "  expected requirements cited (broad: at least one; others: all): "
        f"{hits}/{len(answered)}",
    ]
    for row in no_citation:
        lines.append(f"    no citation: {row['case']['id']}")
    for row in invented:
        lines.append(f"    not in sources: {row['case']['id']} cites {', '.join(row['check']['outside_sources'])}")
    for row in answered:
        if headline_hit(row["case"]["type"], *expected_cited(row)):
            continue
        missing = [rid for rid in row["case"]["expected"] if rid not in row["check"]["cited"]]
        notes = [
            f"{rid} ({'in sources' if rid in row['retrieved'] else 'not retrieved'})"
            for rid in missing
        ]
        lines.append(f"    expected not cited: {row['case']['id']} [{row['case']['type']}] {', '.join(notes)}")
    if unscorable:
        lines.append(
            "  not scored (expected only an introduction): "
            + ", ".join(row["case"]["id"] for row in unscorable)
        )
    return lines


def format_report(rows: list[dict]) -> str:
    skipped = [row for row in rows if row["check"] is None]
    lines = ["Refusals (the fixed \"could not find\" reply):", *format_refusals(rows)]
    lines += ["", "Citations:", *format_citations(rows)]
    if any(row["case"].get("partial") for row in rows):
        lines += ["", "Partly answerable (the unanswered half needs reading by hand):", *format_partial(rows)]
    if skipped:
        lines += ["", f"{len(skipped)} questions have no answer in this report:"]
        lines += [f"  {row['case']['id']}: {row['status']}" for row in skipped]
    return "\n".join(lines)


def main() -> None:
    args = build_parser().parse_args()
    if args.k < 1:
        raise SystemExit("--k must be at least 1")
    cases = load_cases(args)
    assistant = Assistant.from_files(
        args.chunks,
        args.index_dir,
        args.embedding_model,
        model=args.model,
        k=args.k,
        offline=args.cached_only,
    )
    cache = AnswerCache(args.index_dir / ANSWER_CACHE_NAME)
    introductions = {
        chunk["requirement_id"]
        for chunk in assistant.chunks
        if chunk["record_type"] == "requirement_introduction"
    }
    rows = []
    for case in cases:
        rows.append(run_case(assistant, cache, case, args.cached_only, introductions))
        print(f"{case['id']}: {rows[-1]['status']}", file=sys.stderr, flush=True)
    print(f"\nanswer model: {args.model} | k={args.k} | questions: {len(cases)}")
    print(format_report(rows))


if __name__ == "__main__":
    main()
