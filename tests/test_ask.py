"""Answer pipeline: prompt building and citation checks, without calling a model."""

import json
import os

import pytest

from conftest import run_ask

NOT_FOUND = "I could not find this in the retrieved PCI DSS requirements."


def chunk(requirement_id, text, group="requirement", record_type="requirement"):
    return {
        "chunk_id": f"{requirement_id}/{group}/1",
        "record_type": record_type,
        "requirement_id": requirement_id,
        "header": f"PCI DSS v4.0.1 — Requirement {requirement_id} — {group}\nextra context",
        "text": text,
    }


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ask")
    chunks_path = directory / "chunks.jsonl"
    rows = [
        chunk("8.4.2", "MFA is implemented for all non-console access into the CDE."),
        chunk("8.4.2", "8.4.2.a Examine system configurations to verify MFA.", group="testing"),
        chunk("8.4.3", "MFA is implemented for all remote access."),
        chunk("10.5.1", "Retain audit log history for at least 12 months."),
        chunk("3", "Protect stored account data.", group="introduction",
              record_type="requirement_introduction"),
    ]
    chunks_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return {"chunks": str(chunks_path), "index": str(directory / "index")}


def ask(tiny, *args, env=None):
    return run_ask(
        ["--chunks", tiny["chunks"], "--index-dir", tiny["index"], *args], env=env
    )


def test_dry_run_prints_rules_sources_and_question_without_calling_a_model(tiny):
    result = ask(tiny, "How long must audit logs be kept?", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "ONLY the sources provided" in result.stdout
    assert NOT_FOUND in result.stdout
    assert '<source id="10.5.1" kind="requirement">' in result.stdout
    assert "Question: How long must audit logs be kept?" in result.stdout


def test_a_requirement_id_in_the_question_is_retrieved_first(tiny):
    result = ask(tiny, "What does 8.4.3 say?", "--dry-run")

    assert "retrieved: 8.4.3" in result.stdout


def test_all_chunks_of_a_retrieved_requirement_are_in_its_source(tiny):
    result = ask(tiny, "What does 8.4.2 say?", "--dry-run", "--k", "1")
    source = result.stdout.split('<source id="8.4.2"')[1].split("</source>")[0]

    assert "non-console access" in source
    assert "8.4.2.a" in source


def test_k_limits_the_number_of_sources(tiny):
    result = ask(tiny, "What does 8.4.2 say?", "--dry-run", "--k", "2")

    assert result.stdout.count("<source id=") == 2


def test_introductions_are_marked_so_they_are_not_presented_as_requirements(tiny):
    result = ask(tiny, "What does Requirement 3 cover?", "--dry-run", "--k", "1")

    assert '<source id="3" kind="introduction">' in result.stdout


def test_valid_citations_pass_the_check(tiny):
    result = ask(tiny, "What does 8.4.2 say?", "--use-answer", "MFA is required [8.4.2].", "--k", "2")

    assert "check: cited: 8.4.2" in result.stdout
    assert "WARNING" not in result.stdout


def test_citation_of_a_requirement_that_was_not_retrieved_is_flagged(tiny):
    result = ask(
        tiny, "What does 8.4.2 say?", "--use-answer", "See [8.4.2] and [10.5.1].", "--k", "1"
    )

    assert "WARNING cited but not retrieved: 10.5.1" in result.stdout


def test_several_ids_in_one_bracket_are_all_checked(tiny):
    result = ask(
        tiny, "What does 8.4.2 say?", "--use-answer", "MFA applies [8.4.2, 8.4.3].", "--k", "2"
    )

    assert "cited: 8.4.2, 8.4.3" in result.stdout


def test_answer_without_citations_is_flagged(tiny):
    result = ask(tiny, "What does 8.4.2 say?", "--use-answer", "MFA is required.")

    assert "WARNING no citations" in result.stdout


def test_the_not_found_reply_is_recognised(tiny):
    result = ask(tiny, "Which consultancy should we hire?", "--use-answer", NOT_FOUND)

    assert "could not find an answer" in result.stdout
    assert "WARNING" not in result.stdout


def test_unknown_evaluation_question_ids_are_rejected(tiny):
    result = ask(tiny, "--from-eval", "q999", "--dry-run")

    assert result.returncode != 0
    assert "q999" in result.stderr


def test_evaluation_questions_can_be_asked_by_id(tiny):
    result = ask(tiny, "--from-eval", "q02", "u01", "--dry-run")

    assert "=== q02 Explain PCI DSS 10.5.1." in result.stdout
    assert "=== u01 Roughly how much would it cost" in result.stdout


def test_missing_claude_command_fails_with_a_clear_message(tiny):
    env = {**os.environ, "PATH": ""}
    result = ask(tiny, "What does 8.4.2 say?", env=env)

    assert result.returncode != 0
    assert "Generation failed" in result.stderr
    assert "`claude` command was not found" in result.stderr


def test_a_question_or_eval_ids_are_required(tiny):
    result = ask(tiny)

    assert result.returncode != 0
