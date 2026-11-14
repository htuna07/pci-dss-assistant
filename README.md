# PCI DSS Assistant

A RAG assistant that retrieves content from PCI DSS v4.0.1 so an LLM can answer compliance questions accurately and consistently.

## Status

- Done: extraction of the PDF into structured JSON (one file per requirement).
- Done: chunking, keyword / semantic / hybrid retrieval, and a retrieval evaluation set (53 questions plus 3 the standard does not answer).
- Done: query rewriting, where a model rephrases the question in the standard's terminology before searching (53-question evaluation at k=8: 47 fully covered, plain hybrid search 41).
- Done (proof of concept): `ask.py` answers a question from the top 8 retrieved requirements, with citations.
- Planned: answer-quality evaluation, larger question set. Ideas: stop the rewrite from adding topics the question did not ask about; log live usage (with card numbers masked) to grow the evaluation set.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # use requirements.txt to skip pytest
```

Place the official PDF at `data/PCI-DSS-v4_0_1.pdf`. The first semantic search downloads the embedding model (`BAAI/bge-base-en-v1.5`) and caches the chunk embeddings under `data/index/`. Answer generation and query rewriting need the `claude` CLI installed and logged in.

## Usage

```bash
# Dump the text blocks of a page (for debugging the extraction)
python src/main.py --page 44 --inspect

# Extract all requirements found in a page range (full document: 42 337)
python src/main.py --pages 90 120 --extract

# Trace every page decision and show tracebacks on failure
python src/main.py --pages 90 120 --extract --verbose
```

```bash
# Chunk the extracted records (data/processed -> data/chunks/chunks-grouped.jsonl)
python src/build_chunks.py

# Compare keyword, semantic and hybrid retrieval on eval/questions.jsonl
python src/evaluate.py --misses hybrid_id

# Also try model-rewritten queries (one model call per question, cached in data/index/rewrites.json)
python src/evaluate.py --methods hybrid_id hybrid_rewrite --k 8

# Answer a question from the retrieved requirements (--dry-run shows the prompt only; --no-rewrite skips query rewriting)
python src/ask.py "How long must audit logs be kept?"
```

Log messages go to stderr and `Saved:` lines go to stdout. Use `--output-dir` to write somewhere other than `data/processed/`.

`--page` and `--pages` use the PDF viewer's 1-based page numbers, not the printed page numbers, which differ because of the front matter.

## Output

Extracted records are written to `data/processed/requirement-<id>.json` (chunks go to `data/chunks/`, embeddings to `data/index/`; all gitignored):

- `requirement`: one record per requirement (e.g. `3.7.1`) with the defined requirement, testing procedures, customized approach objective, applicability notes, and guidance.
- `requirement_introduction`: one record per top-level requirement (e.g. `9`) with its title, sections, and overview.

The extraction aborts without writing anything if any page in the selected range fails to parse. Errors name the PDF page, requirement, and column, and suggest the matching `--inspect` command.

## Tests

```bash
python -m pytest
```

The tests run the CLI against the real PDF. They check every record against reference output in `tests/golden/` (detects behavior changes; these files contain the standard's text, so they are gitignored and those tests skip when the folder is absent), against an independent typography-based reading of the PDF (detects wrong output), and against hand-verified values for tricky pages. Chunking, retrieval evaluation and `ask.py` have their own tests; the model call itself is not tested (`--dry-run` and `--use-answer` cover the rest). They are skipped when the PDF is missing.
