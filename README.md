# PCI DSS Assistant

A RAG assistant that retrieves content from PCI DSS v4.0.1 so an LLM can answer compliance questions accurately and consistently.

## Status

- Done: extraction of the PDF into structured JSON (one file per requirement).
- Planned: chunking, embeddings, vector store, retrieval, answer generation, evaluation.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Place the official PDF at `data/PCI-DSS-v4_0_1.pdf`.

## Usage

```bash
# Dump the text blocks of a page (for debugging the extraction)
python src/main.py --page 44 --inspect

# Extract all requirements found in a page range
python src/main.py --pages 90 120 --extract
```

`--page` and `--pages` use the PDF viewer's 1-based page numbers, not the printed page numbers, which differ because of the front matter.

## Output

Extracted records are written to `data/processed/requirement-<id>.json`:

- `requirement`: one record per requirement (e.g. `3.7.1`) with the defined requirement, testing procedures, customized approach objective, applicability notes, and guidance.
- `requirement_introduction`: one record per top-level requirement (e.g. `9`) with its title, sections, and overview.

The extraction aborts without writing anything if any page in the selected range fails to parse.
