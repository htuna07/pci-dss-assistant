# PCI DSS Assistant

RAG assistant that retrieves PCI DSS v4.0.1 content so an LLM answers compliance questions accurately and consistently.

## Status

- Done: extraction (PDF → structured JSON), chunking (JSON → JSONL chunks).
- Done: evaluation question set (`eval/questions.jsonl`, 53 English questions plus 3 unanswerable), keyword / semantic / hybrid search with a comparison command.
- Done: query rewriting (`hybrid_rewrite`): a model turns the question into 1–3 queries in the standard's terminology; on the 53 questions at k=8 it fully covers 47 (plain `hybrid_id`: 41).
- Done (proof of concept): `ask.py` answers a question from the top 8 retrieved requirements via `claude -p` (Sonnet 5.5), with citations and a "could not find" reply.
- Not started: answer-quality evaluation (groundedness judge, human-checked sample), larger question set, indexing the PCI DSS scope section (outside pages 42–337).
- Ideas, not decided:
  - Rewrite prompt: the model sometimes adds a topic the question did not ask about (q19); add a "do not add topics" rule and re-measure.
  - Live usage: log question, rewritten queries, retrieved requirements, answer, "could not find" flag and a thumbs up/down, with card-number-like digit runs masked before saving (users may paste real PANs). Use it to grow the evaluation set and to find retrieval misses. Fine-tuning is unlikely to be needed.
  - LLM query routing only if the regex ID shortcut proves too weak.

## Language

- All code, comments, identifiers, docs, prompts, commit messages, and generated output are in English.
- Conversation with the user may be Turkish or English.
- The assistant is English-only for now (the source PDF is English); questions and answers are in English.

## Layout

- `src/main.py` — CLI (`--inspect`, `--extract`, `--output-dir`, `--verbose`).
- `src/config.py` — PDF layout constants (column bounds, page geometry, headings, label corrections).
- `src/extract.py` — page-range walk, continuation handling, the page 281 guidance exception.
- `src/table.py` — three-column table parsing (segments, columns, record assembly).
- `src/introduction.py` — per-requirement introduction parsing.
- `src/errors.py` — `ExtractionError` carrying page / requirement / column context; `ChunkingError` for records that cannot be chunked without losing text.
- `src/chunking.py` — records → chunks (strategies `per_record`, `grouped`, `per_field`; splits only between fields).
- `src/bm25.py` — dependency-free Okapi BM25 (keyword search) and the tokenizer (keeps IDs like `8.4.2` whole).
- `src/embeddings.py` — sentence embeddings (`bge-base-en-v1.5`) for chunks and queries, cached under `data/index/` keyed by a hash of model + chunk text.
- `src/search.py` — `Retriever`: `keyword`, `semantic`, `hybrid` (reciprocal rank fusion), `hybrid_id` (requirement IDs named in the query, validated against known IDs, go first, then hybrid results) and `hybrid_rewrite` (IDs from the original question first, then the hybrid results of each rewritten query fused); returns requirement IDs.
- `src/rewrite.py` — `QueryRewriter`: asks the model for 1–3 queries in PCI DSS terminology, caches them in `data/index/rewrites.json`, and falls back to the original question when the model call or its reply fails (`cache_only` never calls the model).
- `src/evaluate.py` — runs the methods over `eval/questions.jsonl` and prints how many questions have all / at least one expected requirement in the top k. `hybrid_rewrite` is opt-in because it calls a model once per uncached question.
- `src/generate.py` — answer prompt (sources + rules), `claude -p` call (no tools, run from an empty directory, `--restricted`), citation check.
- `src/ask.py` — end-to-end CLI: rewrite the question, retrieve (`hybrid_rewrite`, or `hybrid_id` with `--no-rewrite`), build the prompt from the whole records of the top-k requirements, generate, check citations (`--dry-run`, `--use-answer`, `--from-eval`; the last two never call a model and only reuse cached rewrites).
- `src/build_chunks.py` — chunk CLI (`--strategy`, `--max-words`, `--input-dir`, `--output-dir`).
- `eval/questions.jsonl` — retrieval evaluation set. Fields: `id`, `question`, `language`, `type`, `expected_requirement_ids` (core requirements that directly answer it); optional `persona` (who asks; not part of the searched text) and `related_requirement_ids` (helpful but unscored).
- `eval/unanswerable.jsonl` — questions the standard does not answer; kept apart because they have no expected requirement. For the answer-generation stage, which must say the document does not cover them.
- `tests/` — behavioral tests; `tests/golden/` holds the reference output (gitignored except `evaluate_keyword.stdout`, because it contains the licensed PDF's text; golden tests skip when absent).
- `data/PCI-DSS-v4_0_1.pdf` — source document (gitignored).
- `data/processed/` — extracted JSON, one file per record (gitignored; regenerate from the PDF).
- `data/index/` — cached chunk embeddings (gitignored; rebuilt automatically).
- `data/chunks/` — `chunks-<strategy>.jsonl`, one chunk per line (gitignored; regenerate from `data/processed/`).
- `.venv/` — local virtualenv.

## Commands

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
python src/main.py --page 44 --inspect          # dump text blocks of a page
python src/main.py --pages 42 337 --extract     # full document -> data/processed/requirement-<id>.json
python src/main.py --pages 90 120 --extract -v  # per-page DEBUG trace, tracebacks on failure
python src/build_chunks.py                      # data/processed -> data/chunks/chunks-grouped.jsonl
python src/build_chunks.py --strategy per_field # also: per_record
python src/evaluate.py --misses hybrid         # keyword vs semantic vs hybrid vs hybrid_id on the questions
python src/evaluate.py --methods hybrid_id hybrid_rewrite --k 8   # adds model-rewritten queries (cached after the first run)
python src/ask.py "How long must audit logs be kept?"   # needs the `claude` CLI logged in
python src/ask.py --from-eval q11 u01 --dry-run          # show the prompt only, no model call
python src/ask.py "..." --no-rewrite                     # search with the question as typed
python -m pytest                                # behavioral tests (skipped if the PDF is missing)
```

The full requirement range is PDF pages 42–337. Decision logs go to stderr; `Saved:` lines go to stdout.

`--page`/`--pages` are 1-based PDF viewer pages, not printed page numbers.

## Data Model

Files are `data/processed/requirement-<id>.json`; 262 total, discriminated by `record_type`:

- `requirement` (250): `requirement_id` (e.g. `3.7.1`), `section_id`, `defined_requirement`, `testing_procedures`, `customized_approach_objective`, `applicability_notes`, `guidance` (dict: purpose, good_practice, definitions, examples, further_information; keys present only when found), `pdf_pages`, `extraction_notes`, `document_version`.
- `requirement_introduction` (12): `requirement_id` (e.g. `9`), `title`, `sections` (id + title), `overview`, `notes`, `category_title`, `pdf_pages`, `document_version`.

## Evaluation Notes

- Judge `broad` questions ("how should I set up…") by "at least one expected requirement in the top k"; judge specific multi-part questions by "all expected". The report prints both, overall and per question type.
- Measured on the 53 questions at k=8 (all expected / at least one): `hybrid_id` 41/46, `hybrid_rewrite` 47/53; three rewrite runs gave 45–47 fully covered. Re-weighting keyword vs semantic in the fusion barely moved the totals, so the weights stay equal.
- Rewriting works partly because the model already knows PCI DSS terminology. For an internal document, give the rewrite prompt example passages or a glossary and re-measure.
- When writing questions: one intent each, no requirement IDs or PCI jargon, spread across the 12 principal requirements, and some that the standard does not answer.

## Chunk Model

Each JSONL line: `chunk_id` (`<requirement_id>/<group>/<n>`), `record_type`, `requirement_id`, `section_id`, `group`, `pdf_pages`, `document_version`, `header`, `text`.

- `header` (document version, requirement ID, group, principal-requirement and section titles) is context for embedding and BM25; `text` is the passage shown to the LLM.
- Default strategy `grouped`: `requirement` (defined requirement + customized approach objective + applicability notes), `testing`, `guidance` (all guidance keys). Introductions are one `introduction` group and are never rule sources.
- `--max-words` (default 350) splits a group only between fields, marks pieces "(part n of m)", and logs WARNING for a single field that cannot be split. The default keeps every requirement/testing group whole.
- Retrieval should be able to expand a hit to all chunks sharing its `requirement_id` (planned, not built).

## Extraction Notes

- The PDF is a 3-column table: requirement / testing / guidance. Columns are split by x-coordinate (`COLUMN_BOUNDS`); section headings map to fields via `COLUMN_HEADINGS`.
- Records spanning pages are merged via "(continued)" labels. Known label errors in the PDF are patched in `CONTINUATION_CORRECTIONS`.
- Extraction fails loudly (`ExtractionError` → `SystemExit`) and writes nothing unless the whole range parses. Keep this behavior.
- Raise `ExtractionError` with page, requirement ID, column, and a text excerpt where known; never a bare `ValueError`.
- Decisions that deviate from the raw PDF (label corrections, the page 281 guidance duplication) are logged at WARNING; page-level tracing is DEBUG.

## Testing

- Tests drive the CLI as a subprocess against the real PDF and compare with `tests/golden/` (every record, `Saved:` report, decision log, inspect output) plus structural invariants. They never import extraction internals, so internals can be refactored freely.
- A golden diff means behavior changed, not that it is wrong. Correctness is checked separately: `tests/test_independent_oracle.py` compares every record with `tests/pdf_oracle.py` (reads the PDF by typography only, shares no code with `src/`), and `tests/test_sampled_expectations.py` holds values read by hand from specific PDF pages (structure in the file; quoted text in the gitignored `tests/golden/sampled_expectations.json`, text checks skip when it is absent).
- Regenerate golden files only after confirming the change is intentional and reviewing the diff.
- Never commit text from the PDF (golden records, chunks, extracted JSON): PCI SSC holds the copyright and the repository is public.
- The PDF prints the "Good Practice" heading inline after the Purpose text for 12.3.3 and 12.3.4; `split_inline_heading` in `src/table.py` handles it.
- The 7.1.2 label on PDF page 169 is a genuine PDF error (it belongs to 7.2.1) and is handled by `CONTINUATION_CORRECTIONS`; the oracle ignores continuation labels so it does not depend on it.
- Never point tests at `data/processed/`; they use `--output-dir`.

## Conventions

- Python 3, type hints, `pathlib`, standard library where possible; add dependencies to `requirements.txt` with version bounds.
- Comments explain WHY only (see global instructions).
- Preserve `requirement_id`, `pdf_pages`, and `document_version` on every record and downstream chunk, so answers can cite the exact requirement.
- RAG answers must be grounded in retrieved text and cite requirement IDs; never answer PCI DSS questions from model memory alone.
