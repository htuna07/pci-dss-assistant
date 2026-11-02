"""Build retrieval chunks from extracted requirement records."""

import argparse
import json
import logging
from pathlib import Path

from chunking import STRATEGIES, build_chunks
from config import DEFAULT_CHUNKS_DIR, DEFAULT_MAX_CHUNK_WORDS, DEFAULT_OUTPUT_DIR
from errors import ChunkingError

logger = logging.getLogger("pci_extractor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CHUNKS_DIR)
    parser.add_argument("--strategy", choices=STRATEGIES, default="grouped")
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_CHUNK_WORDS)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def id_sort_key(requirement_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in requirement_id.split("."))


def load_records(input_dir: Path) -> list[dict]:
    paths = sorted(input_dir.glob("requirement-*.json"))
    if not paths:
        raise SystemExit(f"No requirement-*.json files in {input_dir}")
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    return sorted(records, key=lambda record: id_sort_key(record["requirement_id"]))


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )
    if args.max_words < 1:
        raise SystemExit("--max-words must be at least 1")

    records = load_records(args.input_dir)
    try:
        chunks = build_chunks(records, args.strategy, args.max_words)
    except ChunkingError as error:
        logger.debug("Chunking failed", exc_info=True)
        raise SystemExit(f"Chunking failed: {error}") from error

    logger.info(
        "Built %d chunks from %d records with strategy %s",
        len(chunks),
        len(records),
        args.strategy,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"chunks-{args.strategy}.jsonl"
    output_path.write_text(
        "".join(
            json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n" for chunk in chunks
        ),
        encoding="utf-8",
    )
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
