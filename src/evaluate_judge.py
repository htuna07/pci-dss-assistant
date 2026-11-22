"""Exam for the faithfulness judge: real answers must pass, answers with one planted error must not.

Without human labels the judge is only trusted if it finds an error we put there ourselves and
leaves untouched answers alone. The exam file holds answers that may quote the standard, so it
lives under the gitignored data/ folder."""

import argparse
import json
import sys
from pathlib import Path

from config import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_ANSWER_TOP_K,
    DEFAULT_CHUNKS_DIR,
    DEFAULT_INDEX_DIR,
    EMBEDDING_MODEL,
)
from errors import GenerationError
from judge import DEFAULT_JUDGE_MODEL, JUDGE_CACHE_NAME, JudgmentCache, flagged, judge_answer
from pipeline import Assistant


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exam", type=Path, default=DEFAULT_INDEX_DIR / "judge-exam.json",
        help="items: id, planted, kind, marker (the planted wording), question, answer",
    )
    parser.add_argument(
        "--chunks", type=Path, default=DEFAULT_CHUNKS_DIR / "chunks-grouped.jsonl"
    )
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--k", type=int, default=DEFAULT_ANSWER_TOP_K)
    parser.add_argument("--ids", nargs="+", metavar="ID", help="only these exam items")
    parser.add_argument(
        "--cached-only", action="store_true",
        help="never call a model: use cached judgments, report the rest as not run",
    )
    return parser


def run_item(assistant, cache, item, judge_model, cached_only) -> dict:
    # The sources are rebuilt from the question, so the judge sees what the answerer saw.
    prepared = assistant.prepare(item["question"])
    row = {"item": item, "claims": None, "status": "ok"}
    try:
        row["claims"] = judge_answer(
            cache, judge_model, item["question"], prepared.sources, item["answer"], cached_only
        )
    except GenerationError as error:
        row["status"] = f"error: {error}"
        return row
    if row["claims"] is None:
        row["status"] = "not run"
    return row


def hits_marker(claims: dict, marker: str) -> bool:
    """The planted wording sits in a flagged claim, so the judge found our error and not some
    other discrepancy."""
    needle = marker.lower()
    return any(needle in claim["text"].lower() for claim in flagged(claims))


def format_report(rows: list[dict]) -> str:
    done = [row for row in rows if row["claims"] is not None]
    clean = [row for row in done if not row["item"]["planted"]]
    planted = [row for row in done if row["item"]["planted"]]

    lines = ["Untouched answers (the judge should find nothing wrong):"]
    lines.append(
        f"  no claim flagged: {sum(not flagged(row['claims']) for row in clean)}/{len(clean)}"
    )
    for row in clean:
        for claim in flagged(row["claims"]):
            lines.append(f"  flagged in {row['item']['id']} [{claim['verdict']}]: {claim['text']}")

    lines += ["", "Answers with one planted error (the judge should flag it):"]
    caught_any = sum(bool(flagged(row["claims"])) for row in planted)
    caught_right = sum(hits_marker(row["claims"], row["item"]["marker"]) for row in planted)
    lines.append(f"  flagged anywhere:           {caught_any}/{len(planted)}")
    lines.append(f"  flagged at the planted claim: {caught_right}/{len(planted)}")
    for kind in sorted({row["item"]["kind"] for row in planted}):
        group = [row for row in planted if row["item"]["kind"] == kind]
        found = sum(hits_marker(row["claims"], row["item"]["marker"]) for row in group)
        lines.append(f"    {kind}: {found}/{len(group)}")
    for row in planted:
        if not hits_marker(row["claims"], row["item"]["marker"]):
            lines.append(
                f"  missed {row['item']['id']} [{row['item']['kind']}], planted: {row['item']['marker']!r}"
            )

    skipped = [row for row in rows if row["claims"] is None]
    if skipped:
        lines += ["", f"{len(skipped)} items have no judgment:"]
        lines += [f"  {row['item']['id']}: {row['status']}" for row in skipped]
    return "\n".join(lines)


def main() -> None:
    args = build_parser().parse_args()
    items = json.loads(args.exam.read_text(encoding="utf-8"))
    if args.ids:
        unknown = [item_id for item_id in args.ids if item_id not in {i["id"] for i in items}]
        if unknown:
            raise SystemExit(f"Unknown exam ids: {', '.join(unknown)}")
        items = [item for item in items if item["id"] in args.ids]
    assistant = Assistant.from_files(
        args.chunks, args.index_dir, args.embedding_model,
        model=DEFAULT_ANSWER_MODEL, k=args.k, offline=True,
    )
    cache = JudgmentCache(args.index_dir / JUDGE_CACHE_NAME)
    rows = []
    for item in items:
        rows.append(run_item(assistant, cache, item, args.judge_model, args.cached_only))
        print(f"{item['id']}: {rows[-1]['status']}", file=sys.stderr, flush=True)
    print(f"\njudge model: {args.judge_model} | k={args.k} | items: {len(items)}")
    print(format_report(rows))


if __name__ == "__main__":
    main()
