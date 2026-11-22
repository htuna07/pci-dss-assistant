"""Runs the faithfulness judge over every cached answer of the answer-level evaluation.

Answers come from the cache of evaluate_answers.py and are never regenerated here, so the numbers
describe exactly the answers that evaluation reported."""

import sys
from collections import Counter

from config import DEFAULT_ANSWER_MODEL, NOT_FOUND_REPLY
from errors import GenerationError
from evaluate_answers import ANSWER_CACHE_NAME, AnswerCache, build_parser, load_cases
from judge import DEFAULT_JUDGE_MODEL, JUDGE_CACHE_NAME, JudgmentCache, flagged, judge_answer
from pipeline import Assistant


def parse_args():
    parser = build_parser()
    parser.description = __doc__
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    return parser.parse_args()


def judge_case(assistant, answers, judgments, case, judge_model, cached_only) -> dict:
    prepared = assistant.prepare(case["question"])
    text = answers.get(AnswerCache.key(assistant.model, prepared.user_prompt))
    row = {"case": case, "claims": None, "status": "ok", "text": text}
    if text is None:
        row["status"] = "no cached answer"
        return row
    if text.strip() == NOT_FOUND_REPLY:
        # No claims to check, and a judge call would only cost tokens.
        row["claims"] = {"checked": 0, "problems": []}
        return row
    try:
        row["claims"] = judge_answer(judgments, judge_model, case["question"], prepared.sources, text, cached_only)
    except GenerationError as error:
        row["status"] = f"error: {error}"
        return row
    if row["claims"] is None:
        row["status"] = "not run"
    return row


def group_name(case: dict) -> str:
    if case.get("partial"):
        return "partly answerable"
    return "answerable" if case["answerable"] else "unanswerable"


def format_report(rows: list[dict]) -> str:
    done = [row for row in rows if row["claims"] is not None]
    lines = []
    for name in ("answerable", "partly answerable", "unanswerable"):
        group = [row for row in done if group_name(row["case"]) == name]
        if not group:
            continue
        clean = sum(not flagged(row["claims"]) for row in group)
        claims = sum(row["claims"]["checked"] for row in group)
        lines.append(f"{name}: {clean}/{len(group)} answers with every claim supported ({claims} claims)")

    verdicts = Counter(claim["verdict"] for row in done for claim in flagged(row["claims"]))
    checked = sum(row["claims"]["checked"] for row in done)
    verdicts["supported"] = checked - sum(verdicts.values())
    lines.append("claims by verdict: " + ", ".join(f"{name} {count}" for name, count in verdicts.most_common()))

    problem_rows = [row for row in done if flagged(row["claims"])]
    if problem_rows:
        lines += ["", "Flagged claims (read these):"]
    for row in problem_rows:
        lines.append(f"{row['case']['id']} [{group_name(row['case'])}] {row['case']['question']}")
        for claim in flagged(row["claims"]):
            lines.append(f"  {claim['verdict']}: {claim['text']}")
            if claim.get("evidence"):
                lines.append(f"    source says: {claim['evidence']}")

    skipped = [row for row in rows if row["claims"] is None]
    if skipped:
        lines += ["", f"{len(skipped)} answers have no judgment:"]
        lines += [f"  {row['case']['id']}: {row['status']}" for row in skipped]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    cases = load_cases(args)
    assistant = Assistant.from_files(
        args.chunks, args.index_dir, args.embedding_model,
        model=args.model or DEFAULT_ANSWER_MODEL, k=args.k, offline=True,
    )
    answers = AnswerCache(args.index_dir / ANSWER_CACHE_NAME)
    judgments = JudgmentCache(args.index_dir / JUDGE_CACHE_NAME)
    rows = []
    for case in cases:
        rows.append(judge_case(assistant, answers, judgments, case, args.judge_model, args.cached_only))
        print(f"{case['id']}: {rows[-1]['status']}", file=sys.stderr, flush=True)
    print(f"\njudge model: {args.judge_model} | answers from: {assistant.model} | questions: {len(cases)}")
    print(format_report(rows))


if __name__ == "__main__":
    main()
