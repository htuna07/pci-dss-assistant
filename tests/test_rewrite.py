"""Query rewriting: a fake `claude` command stands in for the model, so no real call is made."""

import json
import os
import re
import stat
import sys

import pytest

from conftest import run_ask, run_evaluator

FAKE_CLAUDE = f"""#!{sys.executable}
import json, os, sys

prompt = sys.stdin.read()
kind = "rewrite" if prompt.startswith("Question: ") else "answer"
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as log:
    log.write(kind + "\\n")

if kind == "rewrite" and os.environ.get("FAKE_REWRITE") == "fail":
    sys.exit(1)
if kind == "rewrite" and os.environ.get("FAKE_REWRITE") == "garbage":
    result = "not json at all"
elif kind == "rewrite":
    result = json.dumps({{"queries": json.loads(os.environ["FAKE_QUERIES"])}})
else:
    result = "MFA is required [8.4.2]."
print(json.dumps({{"result": result}}))
"""

QUESTION = "What must remote users use to log in?"
REWRITTEN = "multi-factor authentication for remote access"


def chunk(requirement_id, text):
    return {
        "chunk_id": f"{requirement_id}/requirement/1",
        "record_type": "requirement",
        "requirement_id": requirement_id,
        "header": f"header {requirement_id}",
        "text": text,
    }


@pytest.fixture
def world(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    rows = [
        chunk("8.4.2", "MFA is implemented for all non-console access into the CDE."),
        chunk("8.4.3", "MFA is implemented for all remote access."),
        chunk("10.5.1", "Retain audit log history for at least 12 months."),
        chunk("3.2.1", "Account data storage is kept to a minimum."),
    ]
    chunks_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    log = tmp_path / "calls.log"
    return {
        "chunks": str(chunks_path),
        "index": str(tmp_path / "index"),
        "bin": str(bin_dir),
        "log": log,
        "cache": tmp_path / "index" / "rewrites.json",
        "dir": tmp_path,
    }


def environment(world, queries=(REWRITTEN,), rewrite=None):
    env = dict(os.environ)
    env["PATH"] = world["bin"] + os.pathsep + env["PATH"]
    env["FAKE_CLAUDE_LOG"] = str(world["log"])
    env["FAKE_QUERIES"] = json.dumps(list(queries))
    if rewrite:
        env["FAKE_REWRITE"] = rewrite
    return env


def calls(world):
    return world["log"].read_text().split() if world["log"].exists() else []


def ask(world, *args, **env_options):
    return run_ask(
        ["--chunks", world["chunks"], "--index-dir", world["index"], *args],
        env=environment(world, **env_options),
    )


def test_rewritten_queries_are_shown_and_cached(world):
    first = ask(world, QUESTION)

    assert first.returncode == 0, first.stderr
    assert f"search queries: {REWRITTEN}" in first.stdout
    assert calls(world) == ["rewrite", "answer"]
    assert list(json.loads(world["cache"].read_text()).values()) == [[REWRITTEN]]

    second = ask(world, QUESTION)

    assert f"search queries: {REWRITTEN}" in second.stdout
    assert calls(world) == ["rewrite", "answer", "answer"]


def test_at_most_three_queries_are_used(world):
    result = ask(world, QUESTION, queries=["a one", "b two", "c three", "d four", "e five"])

    assert "search queries: a one | b two | c three\n" in result.stdout


def test_a_failed_rewrite_falls_back_to_the_question(world):
    result = ask(world, QUESTION, rewrite="fail")

    assert result.returncode == 0, result.stderr
    assert f"search queries: {QUESTION}" in result.stdout
    assert "Rewrite failed" in result.stderr
    assert "cited: 8.4.2" in result.stdout
    assert not world["cache"].exists()
    assert calls(world).count("rewrite") == 1


def test_an_unusable_rewrite_reply_falls_back_to_the_question(world):
    result = ask(world, QUESTION, rewrite="garbage")

    assert f"search queries: {QUESTION}" in result.stdout
    assert "not usable" in result.stderr
    assert not world["cache"].exists()


def test_dry_run_never_calls_the_model(world):
    result = ask(world, QUESTION, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert f"search queries: {QUESTION}" in result.stdout
    assert "No cached rewrite" in result.stderr
    assert calls(world) == []


def test_dry_run_reuses_a_cached_rewrite(world):
    ask(world, QUESTION)
    before = calls(world)

    result = ask(world, QUESTION, "--dry-run")

    assert f"search queries: {REWRITTEN}" in result.stdout
    assert calls(world) == before


def test_no_rewrite_searches_with_the_question_as_typed(world):
    result = ask(world, QUESTION, "--no-rewrite")

    assert "search queries" not in result.stdout
    assert calls(world) == ["answer"]


def test_a_requirement_id_in_the_question_still_comes_first(world):
    result = ask(world, "What does 10.5.1 say?", queries=[REWRITTEN])

    assert re.search(r"^retrieved: 10\.5\.1", result.stdout, re.MULTILINE)


def test_evaluation_rewrites_each_question_once_and_scores_the_rewritten_search(world):
    questions = world["dir"] / "questions.jsonl"
    questions.write_text(
        json.dumps(
            {
                "id": "t1",
                "question": "How long do we hold on to the records of system activity?",
                "language": "en",
                "type": "semantic",
                "expected_requirement_ids": ["10.5.1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    env = environment(world, queries=["Retain audit log history for at least 12 months."])
    result = run_evaluator(
        [
            "--chunks", world["chunks"],
            "--questions", str(questions),
            "--index-dir", world["index"],
            "--methods", "hybrid_rewrite",
            "--k", "1",
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert re.search(r"^hybrid_rewrite\s+1/1\s+1/1$", result.stdout, re.MULTILINE), result.stdout
    assert calls(world) == ["rewrite"]
    assert len(json.loads(world["cache"].read_text())) == 1
