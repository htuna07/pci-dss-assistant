"""Search comparison: scoring math on a tiny corpus plus checks on the real data."""

import json
import re

import pytest

from conftest import PROJECT_ROOT, golden_text, run_evaluator

QUESTION_COUNT = len(
    (PROJECT_ROOT / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines()
)

METHOD_ROW = re.compile(r"^(keyword|semantic|hybrid_id|hybrid)\s+(\d+)/(\d+)\s+(\d+)/(\d+)$")
TYPE_ROW = re.compile(r"^(\w+)\s+(\d+)((?:\s+\d+)+)$")


def parse_methods(stdout: str) -> dict[str, dict[str, int]]:
    rows = {}
    for line in stdout.splitlines():
        match = METHOD_ROW.match(line)
        if match:
            method, complete, total, any_hit, _ = match.groups()
            rows[method] = {"complete": int(complete), "any": int(any_hit), "n": int(total)}
    return rows


def parse_types(
    stdout: str, methods: list[str], table: str = "all expected"
) -> dict[str, dict[str, int]]:
    section = stdout.split(f"{table} in top 5, by question type:")[1]
    rows = {}
    for line in section.split("\n\n")[0].splitlines():
        match = TYPE_ROW.match(line)
        if match:
            name, count, scores = match.groups()
            rows[name] = {"n": int(count), **dict(zip(methods, map(int, scores.split())))}
    return rows


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def make_chunks(path, texts):
    write_jsonl(
        path,
        [
            {
                "chunk_id": f"{name}/requirement/1",
                "requirement_id": name,
                "header": f"header {name}",
                "text": text,
            }
            for name, text in texts.items()
        ],
    )


@pytest.fixture
def tiny_chunks(tmp_path):
    path = tmp_path / "chunks.jsonl"
    make_chunks(
        path,
        {
            "A": "firewall rules are defined",
            "B": "encrypt data at rest",
            "C": "password length twelve",
        },
    )
    return path


def run_keyword(tmp_path, chunks_path, questions, extra=()):
    questions_path = tmp_path / "questions.jsonl"
    write_jsonl(
        questions_path,
        [{"id": f"q{i}", "type": "t", **question} for i, question in enumerate(questions)],
    )
    return run_evaluator(
        [
            "--chunks", str(chunks_path),
            "--questions", str(questions_path),
            "--methods", "keyword",
            *extra,
        ]
    )


def test_perfect_retrieval_counts_as_complete(tmp_path, tiny_chunks):
    result = run_keyword(
        tmp_path,
        tiny_chunks,
        [{"question": "What is the password length?", "expected_requirement_ids": ["C"]}],
    )

    assert result.returncode == 0, result.stderr
    assert parse_methods(result.stdout)["keyword"] == {"complete": 1, "any": 1, "n": 1}


def test_partial_retrieval_is_not_complete_but_counts_as_any(tmp_path, tiny_chunks):
    result = run_keyword(
        tmp_path,
        tiny_chunks,
        [
            {"question": "password", "expected_requirement_ids": ["B", "C"]},
            {"question": "password", "expected_requirement_ids": ["B"]},
        ],
    )

    assert parse_methods(result.stdout)["keyword"] == {"complete": 0, "any": 1, "n": 2}


def test_k_limits_how_deep_the_ranking_counts(tmp_path, tiny_chunks):
    questions = [
        {"question": "firewall encrypt password", "expected_requirement_ids": ["A", "B", "C"]}
    ]

    shallow = run_keyword(tmp_path, tiny_chunks, questions, ["--k", "2"])
    deep = run_keyword(tmp_path, tiny_chunks, questions, ["--k", "3"])

    assert parse_methods(shallow.stdout)["keyword"]["complete"] == 0
    assert parse_methods(deep.stdout)["keyword"]["complete"] == 1


def test_requirement_ids_are_matched_as_whole_tokens(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    make_chunks(chunks_path, {"8.4.2": "alpha", "8.4.3": "beta", "2.4.8": "gamma"})

    result = run_keyword(
        tmp_path,
        chunks_path,
        [{"question": "What does 8.4.3 say?", "expected_requirement_ids": ["8.4.3"]}],
        ["--k", "1"],
    )

    assert parse_methods(result.stdout)["keyword"]["complete"] == 1


def test_misses_lists_failed_questions(tmp_path, tiny_chunks):
    result = run_keyword(
        tmp_path,
        tiny_chunks,
        [{"question": "password", "expected_requirement_ids": ["B"]}],
        ["--misses", "keyword"],
    )

    assert "q0 [t] password" in result.stdout
    assert "expected: B" in result.stdout
    assert "got:      C" in result.stdout


def test_missing_chunks_file_fails(tmp_path):
    result = run_evaluator(["--chunks", str(tmp_path / "nope.jsonl")])

    assert result.returncode != 0
    assert "File not found" in result.stderr


def test_misses_for_a_method_that_did_not_run_is_rejected(tmp_path, tiny_chunks):
    result = run_keyword(
        tmp_path,
        tiny_chunks,
        [{"question": "password", "expected_requirement_ids": ["C"]}],
        ["--misses", "hybrid"],
    )

    assert result.returncode != 0


def test_embedding_cache_is_reused_and_invalidated_by_text_changes(tmp_path, tiny_chunks):
    index_dir = tmp_path / "index"
    questions = tmp_path / "questions.jsonl"
    write_jsonl(
        questions,
        [{"id": "q", "type": "t", "question": "password", "expected_requirement_ids": ["C"]}],
    )
    args = [
        "--chunks", str(tiny_chunks),
        "--questions", str(questions),
        "--methods", "semantic",
        "--index-dir", str(index_dir),
    ]

    assert run_evaluator(args).returncode == 0
    assert run_evaluator(args).returncode == 0
    assert len(list(index_dir.glob("embeddings-*.npy"))) == 1

    make_chunks(tiny_chunks, {"A": "changed text", "B": "encrypt data at rest", "C": "password"})
    assert run_evaluator(args).returncode == 0
    assert len(list(index_dir.glob("embeddings-*.npy"))) == 2


@pytest.fixture(scope="module")
def real_run(chunk_runs, tmp_path_factory):
    chunks_path = chunk_runs["grouped"].output_dir / "chunks-grouped.jsonl"
    return run_evaluator(
        [
            "--chunks", str(chunks_path),
            "--index-dir", str(tmp_path_factory.mktemp("index")),
            "--misses", "hybrid",
        ]
    )


def test_real_data_run_succeeds_for_all_methods(real_run):
    methods = parse_methods(real_run.stdout)

    assert real_run.returncode == 0, real_run.stderr
    assert set(methods) == {"keyword", "semantic", "hybrid", "hybrid_id"}
    assert {row["n"] for row in methods.values()} == {QUESTION_COUNT}


def test_hybrid_is_at_least_as_good_as_each_single_method(real_run):
    methods = parse_methods(real_run.stdout)

    assert methods["hybrid"]["complete"] >= methods["keyword"]["complete"]
    assert methods["hybrid"]["complete"] >= methods["semantic"]["complete"]


def test_id_lookup_questions_are_all_answered_by_hybrid_id(real_run):
    types = parse_types(real_run.stdout, ["keyword", "semantic", "hybrid", "hybrid_id"])

    assert types["id_lookup"]["hybrid_id"] == types["id_lookup"]["n"]


def test_hybrid_id_is_at_least_as_good_as_hybrid(real_run):
    methods = parse_methods(real_run.stdout)

    assert methods["hybrid_id"]["complete"] >= methods["hybrid"]["complete"]


def run_hybrid_id(tmp_path, chunks_path, question, expected):
    questions = tmp_path / "questions.jsonl"
    write_jsonl(
        questions,
        [{"id": "q", "type": "t", "question": question, "expected_requirement_ids": expected}],
    )
    return run_evaluator(
        [
            "--chunks", str(chunks_path),
            "--questions", str(questions),
            "--methods", "hybrid_id",
            "--index-dir", str(tmp_path / "index"),
            "--k", "1",
        ]
    )


def test_mentioned_requirement_id_is_placed_first_even_when_text_is_unrelated(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    make_chunks(chunks_path, {"8.4.2": "alpha", "8.4.3": "beta", "2.4.8": "gamma"})

    result = run_hybrid_id(tmp_path, chunks_path, "Explain 8.4.3 please", ["8.4.3"])

    assert parse_methods(result.stdout)["hybrid_id"]["complete"] == 1


def test_unknown_dotted_numbers_are_not_treated_as_requirement_ids(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    make_chunks(
        chunks_path,
        {"1": "network security", "5.2.1": "firewall rules for network traffic"},
    )

    result = run_hybrid_id(
        tmp_path, chunks_path, "In version 4.0.1 are firewall rules needed?", ["5.2.1"]
    )

    assert parse_methods(result.stdout)["hybrid_id"]["complete"] == 1


def test_principal_requirement_mentions_resolve_to_the_introduction(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    make_chunks(chunks_path, {"3": "overview", "3.5.1": "alpha", "4": "beta"})

    result = run_hybrid_id(tmp_path, chunks_path, "What does Requirement 3 cover?", ["3"])

    assert parse_methods(result.stdout)["hybrid_id"]["complete"] == 1


def test_report_has_a_second_table_for_at_least_one_per_type(real_run):
    methods = ["keyword", "semantic", "hybrid", "hybrid_id"]
    all_rows = parse_types(real_run.stdout, methods)
    any_rows = parse_types(real_run.stdout, methods, "at least one expected")

    assert set(all_rows) == set(any_rows)
    for name, row in all_rows.items():
        for method in methods:
            assert any_rows[name][method] >= row[method]


def test_keyword_search_finds_every_requirement_id_lookup(real_run):
    types = parse_types(real_run.stdout, ["keyword", "semantic", "hybrid", "hybrid_id"])

    assert types["id_lookup"]["keyword"] == types["id_lookup"]["n"]


def test_keyword_report_matches_golden(chunk_runs):
    chunks_path = chunk_runs["grouped"].output_dir / "chunks-grouped.jsonl"
    result = run_evaluator(
        ["--chunks", str(chunks_path), "--methods", "keyword", "--misses", "keyword"]
    )
    expected = golden_text("evaluate_keyword.stdout")

    assert result.stdout == expected
