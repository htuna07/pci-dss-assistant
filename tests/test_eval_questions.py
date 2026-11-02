"""The evaluation question set must stay consistent with the extracted data."""

import json

import pytest

from conftest import PROJECT_ROOT

QUESTIONS_PATH = PROJECT_ROOT / "eval" / "questions.jsonl"
KEYS = {"id", "question", "language", "type", "expected_requirement_ids"}
TYPES = {
    "id_lookup",
    "keyword",
    "semantic",
    "testing",
    "applicability",
    "multi",
    "conceptual",
    "non_technical",
}


def load(path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    return load(QUESTIONS_PATH)


def test_questions_have_the_expected_shape(questions):
    for question in questions:
        assert set(question) == KEYS
        assert question["type"] in TYPES
        assert question["language"] == "en"
        assert question["question"].strip()
        assert question["expected_requirement_ids"]


def test_question_ids_and_texts_are_unique(questions):
    assert len({q["id"] for q in questions}) == len(questions)
    assert len({q["question"] for q in questions}) == len(questions)


def test_expected_ids_exist_in_the_extracted_records(questions, full_extraction):
    known = {
        name.removeprefix("requirement-").removesuffix(".json")
        for name in full_extraction.output_files()
    }

    for question in questions:
        missing = set(question["expected_requirement_ids"]) - known
        assert not missing, f"{question['id']}: unknown requirement ids {missing}"


def test_set_covers_every_question_type(questions):
    assert {q["type"] for q in questions} == TYPES


def test_conceptual_questions_expect_introduction_records(questions, full_extraction):
    for question in questions:
        if question["type"] != "conceptual":
            continue
        for requirement_id in question["expected_requirement_ids"]:
            record = json.loads(
                full_extraction.output_files()[f"requirement-{requirement_id}.json"]
            )
            assert record["record_type"] == "requirement_introduction"
