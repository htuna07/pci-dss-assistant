"""Answer-level evaluation: a fake `claude` command stands in for the model, so no real call is made."""

import json
import os
import stat
import subprocess
import sys

import pytest

from conftest import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "src" / "evaluate_answers.py"
NOT_FOUND = "I could not find this in the retrieved PCI DSS requirements."

# The rewrite prompt starts with "Question: " and the answer prompt with "Sources:".
FAKE_CLAUDE = f"""#!{sys.executable}
import json, os, sys

prompt = sys.stdin.read()
if prompt.startswith("Question: "):
    print(json.dumps({{"result": json.dumps({{"queries": ["audit log retention"]}})}}))
    sys.exit(0)
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as log:
    log.write("answer\\n")
if "refusemore" in prompt:
    result = {NOT_FOUND!r} + "\\n\\nExtra text."
elif "refuse" in prompt:
    result = {NOT_FOUND!r}
elif "invent" in prompt:
    result = "Keep it for a year [99.9.9]."
elif "uncited" in prompt:
    result = "Keep it for a year."
else:
    result = "Keep it for a year [10.5.1]."
print(json.dumps({{"result": result}}))
"""


def chunk(requirement_id, text, record_type="requirement"):
    return {
        "chunk_id": f"{requirement_id}/requirement/1",
        "record_type": record_type,
        "requirement_id": requirement_id,
        "header": f"header {requirement_id}",
        "text": text,
    }


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


@pytest.fixture
def world(tmp_path):
    chunks = tmp_path / "chunks.jsonl"
    write_jsonl(
        chunks,
        [
            chunk("10.5.1", "Retain audit log history for at least 12 months."),
            chunk("3", "Audit log history background.", record_type="requirement_introduction"),
        ],
    )
    questions = tmp_path / "questions.jsonl"
    write_jsonl(
        questions,
        [
            {"id": "q1", "type": "keyword", "question": "How long are audit log history kept?",
             "expected_requirement_ids": ["10.5.1"]},
            {"id": "q2", "type": "keyword", "question": "refuse audit log history",
             "expected_requirement_ids": ["10.5.1"]},
            {"id": "q3", "type": "keyword", "question": "invent audit log history",
             "expected_requirement_ids": ["10.5.1"]},
            {"id": "q4", "type": "keyword", "question": "uncited audit log history",
             "expected_requirement_ids": ["10.5.1"]},
            {"id": "q5", "type": "conceptual", "question": "Explain audit log history basics",
             "expected_requirement_ids": ["3"]},
        ],
    )
    unanswerable = tmp_path / "unanswerable.jsonl"
    write_jsonl(
        unanswerable,
        [
            {"id": "u1", "question": "refuse something about audit log history"},
            {"id": "u2", "question": "What does the audit log history cost?"},
            {"id": "u3", "question": "refusemore about audit log history"},
        ],
    )
    partial = tmp_path / "partial.jsonl"
    write_jsonl(
        partial,
        [
            {"id": "p1", "question": "refuse audit log history and a product",
             "expected_requirement_ids": ["10.5.1"]},
            {"id": "p2", "question": "refusemore audit log history and a product",
             "expected_requirement_ids": ["10.5.1"]},
            {"id": "p3", "question": "audit log history and a product",
             "expected_requirement_ids": ["10.5.1"]},
        ],
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return {"dir": tmp_path, "args": [
        "--chunks", str(chunks), "--questions", str(questions),
        "--unanswerable", str(unanswerable), "--partial", str(partial),
        "--index-dir", str(tmp_path / "index"),
    ]}


def run(world, *extra):
    env = dict(os.environ)
    env["PATH"] = str(world["dir"] / "bin") + os.pathsep + env["PATH"]
    env["FAKE_CLAUDE_LOG"] = str(world["dir"] / "calls.log")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *world["args"], *extra],
        capture_output=True, text=True, encoding="utf-8", cwd=PROJECT_ROOT, env=env,
    )


def answer_calls(world):
    log = world["dir"] / "calls.log"
    return len(log.read_text().split()) if log.exists() else 0


def test_matrix_counts_false_refusals_and_invented_answers(world):
    result = run(world)

    assert result.returncode == 0, result.stderr
    assert "answerable (5)" in result.stdout
    # q2 is the only refused answerable question; u2 is the unanswerable one that got an answer.
    assert "false refusal q2: an expected requirement was among the sources (model or prompt problem)" in result.stdout
    assert "answered although unanswerable: u2" in result.stdout
    assert "answered although unanswerable: u1" not in result.stdout
    assert "refused, then kept writing: u3" in result.stdout
    assert "refused, then kept writing: u1" not in result.stdout


def test_citation_problems_are_listed(world):
    result = run(world)

    assert "without any citation:            1" in result.stdout
    assert "no citation: q4" in result.stdout
    assert "not in sources: q3 cites 99.9.9" in result.stdout
    assert "expected not cited: q3 [keyword] 10.5.1 (in sources)" in result.stdout
    assert "expected requirements cited (broad: at least one; others: all): 1/3" in result.stdout


def test_a_question_expecting_only_an_introduction_is_not_scored_by_citations(world):
    result = run(world)

    assert "not scored (expected only an introduction): q5" in result.stdout
    assert "expected not cited: q5" not in result.stdout


def test_cached_answers_are_reused_and_no_model_is_called_again(world):
    first = run(world)
    calls_after_first = answer_calls(world)
    second = run(world)

    assert calls_after_first == 11
    assert answer_calls(world) == calls_after_first
    assert second.stdout == first.stdout


def test_cached_only_runs_nothing_and_reports_what_is_missing(world):
    result = run(world, "--cached-only")

    assert result.returncode == 0, result.stderr
    assert answer_calls(world) == 0
    assert "11 questions have no answer in this report" in result.stdout
    assert "q1: not run" in result.stdout


def test_unknown_id_is_rejected(world):
    result = run(world, "--ids", "q99")

    assert result.returncode != 0
    assert "Unknown question ids: q99" in result.stderr


def test_partly_answerable_questions_are_judged_apart_from_the_matrix(world):
    result = run(world)

    assert result.returncode == 0, result.stderr
    assert "p1: refused everything (useful part withheld)" in result.stdout
    assert "p2: refusal sentence, then kept writing (mixed signal)" in result.stdout
    assert "p3: answered, expected cited" in result.stdout
    # They must not distort the answerable / unanswerable counts.
    assert "answerable (5)" in result.stdout
