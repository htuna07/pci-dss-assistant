# PCI DSS Assistant

RAG assistant that retrieves PCI DSS v4.0.1 content so an LLM answers compliance questions accurately and consistently.

## Status

- Done: extraction (PDF → structured JSON).
- Not started: chunking, embeddings, vector store, retrieval, LLM answer generation, evaluation.

## Language

- All code, comments, identifiers, docs, prompts, commit messages, and generated output are in English.
- Conversation with the user may be Turkish or English.

## Layout

- `src/main.py` — extraction CLI (PyMuPDF).
- `data/PCI-DSS-v4_0_1.pdf` — source document.
- `data/processed/` — extracted JSON, one file per record (gitignored; regenerate from the PDF).
- `.venv/` — local virtualenv.

## Commands

```bash
source .venv/bin/activate
pip install -r requirements.txt
python src/main.py --page 44 --inspect          # dump text blocks of a page
python src/main.py --pages 90 120 --extract     # write data/processed/requirement-<id>.json
```

`--page`/`--pages` are 1-based PDF viewer pages, not printed page numbers.

## Data Model

Files are `data/processed/requirement-<id>.json`; 262 total, discriminated by `record_type`:

- `requirement` (250): `requirement_id` (e.g. `3.7.1`), `section_id`, `defined_requirement`, `testing_procedures`, `customized_approach_objective`, `applicability_notes`, `guidance` (dict: purpose, good_practice, definitions, examples, further_information; keys present only when found), `pdf_pages`, `extraction_notes`, `document_version`.
- `requirement_introduction` (12): `requirement_id` (e.g. `9`), `title`, `sections` (id + title), `overview`, `notes`, `category_title`, `pdf_pages`, `document_version`.

## Extraction Notes

- The PDF is a 3-column table: requirement / testing / guidance. Columns are split by x-coordinate (`COLUMN_BOUNDS`); section headings map to fields via `COLUMN_HEADINGS`.
- Records spanning pages are merged via "(continued)" labels. Known label errors in the PDF are patched in `CONTINUATION_CORRECTIONS`.
- Extraction fails loudly (`ValueError` → `SystemExit`) and writes nothing unless the whole range parses. Keep this behavior.
- After changing extraction logic, re-run on affected pages and diff `data/processed/` before trusting results.

## Conventions

- Python 3, type hints, `pathlib`, standard library where possible; add dependencies to `requirements.txt` with version bounds.
- Comments explain WHY only (see global instructions).
- Preserve `requirement_id`, `pdf_pages`, and `document_version` on every record and downstream chunk, so answers can cite the exact requirement.
- RAG answers must be grounded in retrieved text and cite requirement IDs; never answer PCI DSS questions from model memory alone.
