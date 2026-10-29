# PCI DSS Assistant

RAG assistant that retrieves PCI DSS v4.0.1 content so an LLM answers compliance questions accurately and consistently.

## Status

- Done: extraction (PDF → structured JSON).
- Not started: chunking, embeddings, vector store, retrieval, LLM answer generation, evaluation.

## Language

- All code, comments, identifiers, docs, prompts, commit messages, and generated output are in English.
- Conversation with the user may be Turkish or English.

## Layout

- `src/main.py` — CLI (`--inspect`, `--extract`, `--output-dir`, `--verbose`).
- `src/config.py` — PDF layout constants (column bounds, page geometry, headings, label corrections).
- `src/extract.py` — page-range walk, continuation handling, the page 281 guidance exception.
- `src/table.py` — three-column table parsing (segments, columns, record assembly).
- `src/introduction.py` — per-requirement introduction parsing.
- `src/errors.py` — `ExtractionError` carrying page / requirement / column context.
- `tests/` — behavioral tests; `tests/golden/` holds the reference output.
- `data/PCI-DSS-v4_0_1.pdf` — source document (gitignored).
- `data/processed/` — extracted JSON, one file per record (gitignored; regenerate from the PDF).
- `.venv/` — local virtualenv.

## Commands

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
python src/main.py --page 44 --inspect          # dump text blocks of a page
python src/main.py --pages 42 337 --extract     # full document -> data/processed/requirement-<id>.json
python src/main.py --pages 90 120 --extract -v  # per-page DEBUG trace, tracebacks on failure
python -m pytest                                # behavioral tests (skipped if the PDF is missing)
```

The full requirement range is PDF pages 42–337. Decision logs go to stderr; `Saved:` lines go to stdout.

`--page`/`--pages` are 1-based PDF viewer pages, not printed page numbers.

## Data Model

Files are `data/processed/requirement-<id>.json`; 262 total, discriminated by `record_type`:

- `requirement` (250): `requirement_id` (e.g. `3.7.1`), `section_id`, `defined_requirement`, `testing_procedures`, `customized_approach_objective`, `applicability_notes`, `guidance` (dict: purpose, good_practice, definitions, examples, further_information; keys present only when found), `pdf_pages`, `extraction_notes`, `document_version`.
- `requirement_introduction` (12): `requirement_id` (e.g. `9`), `title`, `sections` (id + title), `overview`, `notes`, `category_title`, `pdf_pages`, `document_version`.

## Extraction Notes

- The PDF is a 3-column table: requirement / testing / guidance. Columns are split by x-coordinate (`COLUMN_BOUNDS`); section headings map to fields via `COLUMN_HEADINGS`.
- Records spanning pages are merged via "(continued)" labels. Known label errors in the PDF are patched in `CONTINUATION_CORRECTIONS`.
- Extraction fails loudly (`ExtractionError` → `SystemExit`) and writes nothing unless the whole range parses. Keep this behavior.
- Raise `ExtractionError` with page, requirement ID, column, and a text excerpt where known; never a bare `ValueError`.
- Decisions that deviate from the raw PDF (label corrections, the page 281 guidance duplication) are logged at WARNING; page-level tracing is DEBUG.

## Testing

- Tests drive the CLI as a subprocess against the real PDF and compare with `tests/golden/` (every record, `Saved:` report, decision log, inspect output) plus structural invariants. They never import extraction internals, so internals can be refactored freely.
- A golden diff means behavior changed, not that it is wrong. Correctness is checked separately: `tests/test_independent_oracle.py` compares every record with `tests/pdf_oracle.py` (reads the PDF by typography only, shares no code with `src/`), and `tests/test_sampled_expectations.py` holds values read by hand from specific PDF pages.
- Regenerate golden files only after confirming the change is intentional and reviewing the diff.
- Known extraction bug: 12.3.3 and 12.3.4 lose their `good_practice` field because the PDF prints the "Good Practice" heading inline after the Purpose text. Tracked as a strict `xfail`; remove the marker when fixed.
- The 7.1.2 label on PDF page 169 is a genuine PDF error (it belongs to 7.2.1) and is handled by `CONTINUATION_CORRECTIONS`; the oracle ignores continuation labels so it does not depend on it.
- Never point tests at `data/processed/`; they use `--output-dir`.

## Conventions

- Python 3, type hints, `pathlib`, standard library where possible; add dependencies to `requirements.txt` with version bounds.
- Comments explain WHY only (see global instructions).
- Preserve `requirement_id`, `pdf_pages`, and `document_version` on every record and downstream chunk, so answers can cite the exact requirement.
- RAG answers must be grounded in retrieved text and cite requirement IDs; never answer PCI DSS questions from model memory alone.
