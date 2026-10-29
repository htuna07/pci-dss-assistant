"""Inspect PDF pages or extract requirements across multiple pages."""

import argparse
import json
import logging
from pathlib import Path

import pymupdf

from config import DEFAULT_OUTPUT_DIR, PDF_PATH
from errors import ExtractionError
from extract import extract_requirements

logger = logging.getLogger("pci_extractor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--page", type=int)
    selection.add_argument(
        "--pages",
        nargs=2,
        type=int,
        metavar=("START", "END"),
    )

    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--inspect", action="store_true")
    modes.add_argument("--extract", action="store_true")

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log per-page decisions and show tracebacks on failure",
    )
    return parser


def inspect_pages(document: pymupdf.Document, start: int, end: int) -> None:
    for page_number in range(start, end + 1):
        page = document[page_number - 1]
        print(f"\n=== PAGE {page_number} ===")

        for block in page.get_text("blocks", sort=True):
            x0, y0, x1, y1, text, number, kind = block
            if kind == 0 and text.strip():
                print(
                    f"\n--- Block {number} "
                    f"x={x0:.1f}..{x1:.1f} "
                    f"y={y0:.1f}..{y1:.1f} ---"
                )
                print(text.strip())


def summarize(results: list[dict], start: int, end: int) -> str:
    introductions = sum(
        result["record_type"] == "requirement_introduction"
        for result in results
    )
    with_notes = sum(bool(result.get("extraction_notes")) for result in results)
    return (
        f"Extracted {len(results) - introductions} requirements and "
        f"{introductions} introductions from PDF pages {start}-{end}; "
        f"{with_notes} records carry extraction notes"
    )


def explain_failure(error: ExtractionError) -> str:
    message = f"Extraction failed: {error}"
    if error.page is not None:
        message += (
            f"\nInspect the raw page blocks with: "
            f"python src/main.py --page {error.page} --inspect"
        )
    return message


def write_results(results: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for result in results:
        output_path = output_dir / f"requirement-{result['requirement_id']}.json"
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Saved: {output_path}")


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    if not PDF_PATH.is_file():
        raise SystemExit(f"PDF not found: {PDF_PATH}")

    start, end = (
        (args.page, args.page)
        if args.page is not None
        else args.pages
    )

    with pymupdf.open(PDF_PATH) as document:
        if not 1 <= start <= end <= len(document):
            raise SystemExit(
                f"Page range must be within 1..{len(document)}"
            )

        if args.inspect:
            inspect_pages(document, start, end)
            return

        try:
            results = extract_requirements(document, start, end)
        except ExtractionError as error:
            logger.debug("Extraction failed", exc_info=True)
            raise SystemExit(explain_failure(error)) from error

    logger.info(summarize(results, start, end))

    # Write only after the entire selected range parses successfully.
    write_results(results, args.output_dir)


if __name__ == "__main__":
    main()
