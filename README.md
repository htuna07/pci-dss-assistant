# PCI DSS Assistant

A RAG assistant that retrieves content from PCI DSS v4.0.1 so an LLM can answer compliance questions accurately and consistently.

## Status

- Done: extraction of the PDF into structured JSON (one file per requirement).
- Done: chunking, keyword / semantic / hybrid retrieval, and a retrieval evaluation set (53 questions plus 3 the standard does not answer).
- Done: query rewriting, where a model rephrases the question in the standard's terminology before searching (53-question evaluation at k=8: 47 fully covered, plain hybrid search 41).
- Done: a local web interface (`python src/server.py`) with the same pipeline.
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

# Same thing in a browser: http://127.0.0.1:8000 (needs the `claude` CLI logged in; listens on this machine only)
python src/server.py
```

Log messages go to stderr and `Saved:` lines go to stdout. Use `--output-dir` to write somewhere other than `data/processed/`.

`--page` and `--pages` use the PDF viewer's 1-based page numbers, not the printed page numbers, which differ because of the front matter.

## Output

Extracted records are written to `data/processed/requirement-<id>.json` (chunks go to `data/chunks/`, embeddings to `data/index/`; all gitignored):

- `requirement`: one record per requirement (e.g. `3.7.1`) with the defined requirement, testing procedures, customized approach objective, applicability notes, and guidance.
- `requirement_introduction`: one record per top-level requirement (e.g. `9`) with its title, sections, and overview.

The extraction aborts without writing anything if any page in the selected range fails to parse. Errors name the PDF page, requirement, and column, and suggest the matching `--inspect` command.

## Tests and evaluation

```bash
python -m pytest                          # behavioral tests
python src/evaluate.py --misses hybrid    # retrieval evaluation
```

**Tests** run the CLI as a subprocess against the real PDF, so internals can be refactored freely. They cover four things:
- Extraction correctness: an independent reader (`tests/pdf_oracle.py`, no shared code with `src/`) compares every record, and `test_sampled_expectations.py` holds hand-verified values for tricky pages.
- Structural invariants and clear failures for unsupported page ranges (`test_invariants.py`, `test_cli_failures.py`).
- Chunking, search scoring and the answer pipeline (`test_chunking.py`, `test_evaluate.py`, `test_ask.py`, `test_rewrite.py`). The model call is replaced by a fake `claude` command, so no test calls a model.
- Consistency of the question set with the extracted data (`test_eval_questions.py`).

**Evaluation** (`eval/questions.jsonl`, 53 questions) measures retrieval: for each question, are the expected requirement IDs in the top k results? The report counts questions with all and with at least one expected requirement, overall and per question type. `eval/unanswerable.jsonl` holds questions the standard does not answer, for testing the "could not find" reply.

**What is not in this repository.** The PDF, the extracted JSON, the chunks and the reference ("golden") outputs contain the standard's text, which PCI SSC copyrights, so they are gitignored. Download the PDF yourself (see Setup). Tests that compare against golden files or quoted text skip when those files are absent; everything else, including the independent PDF check, runs. Without the PDF all tests skip.
