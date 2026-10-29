# PCI DSS Assistant

A RAG assistant that retrieves content from PCI DSS v4.0.1 so an LLM can answer compliance questions accurately and consistently.

## Status

- Done: extraction of the PDF into structured JSON (one file per requirement), with behavioral tests.
- Planned: chunking, embeddings, vector store, retrieval, answer generation, evaluation.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # use requirements.txt to skip pytest
```

Place the official PDF at `data/PCI-DSS-v4_0_1.pdf`.

## Usage

```bash
# Dump the text blocks of a page (for debugging the extraction)
python src/main.py --page 44 --inspect

# Extract all requirements found in a page range (full document: 42 337)
python src/main.py --pages 90 120 --extract

# Trace every page decision and show tracebacks on failure
python src/main.py --pages 90 120 --extract --verbose
```

Log messages go to stderr and `Saved:` lines go to stdout. Use `--output-dir` to write somewhere other than `data/processed/`.

`--page` and `--pages` use the PDF viewer's 1-based page numbers, not the printed page numbers, which differ because of the front matter.

## Output

Extracted records are written to `data/processed/requirement-<id>.json`:

- `requirement`: one record per requirement (e.g. `3.7.1`) with the defined requirement, testing procedures, customized approach objective, applicability notes, and guidance.
- `requirement_introduction`: one record per top-level requirement (e.g. `9`) with its title, sections, and overview.

The extraction aborts without writing anything if any page in the selected range fails to parse. Errors name the PDF page, requirement, and column, and suggest the matching `--inspect` command.

## Tests

```bash
python -m pytest
```

The tests run the CLI against the real PDF. They check every record against reference output in `tests/golden/` (detects behavior changes), against an independent typography-based reading of the PDF (detects wrong output), and against hand-verified values for tricky pages. They are skipped when the PDF is missing.
