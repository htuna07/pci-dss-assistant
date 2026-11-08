"""The evaluation question set must stay consistent with the extracted data."""

import json

import pytest

from conftest import PROJECT_ROOT

QUESTIONS_PATH = PROJECT_ROOT / "eval" / "questions.jsonl"
REQUIRED_KEYS = {"id", "question", "language", "type", "expected_requirement_ids"}
OPTIONAL_KEYS = {"persona", "related_requirement_ids"}
UNANSWERABLE_PATH = PROJECT_ROOT / "eval" / "unanswerable.jsonl"
TYPES = {
    "id_lookup",
    "keyword",
    "semantic",
    "testing",
    "applicability",
    "multi",
    "conceptual",
    "non_technical",
    "broad",
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
        assert REQUIRED_KEYS <= set(question) <= REQUIRED_KEYS | OPTIONAL_KEYS
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
        referenced = set(question["expected_requirement_ids"]) | set(
            question.get("related_requirement_ids", [])
        )
        missing = referenced - known
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


def test_related_ids_never_repeat_expected_ids(questions):
    for question in questions:
        overlap = set(question["expected_requirement_ids"]) & set(
            question.get("related_requirement_ids", [])
        )
        assert not overlap, f"{question['id']}: {overlap} listed as expected and related"


def test_unanswerable_questions_are_separate_and_expect_no_requirement(questions):
    unanswerable = load(UNANSWERABLE_PATH)

    assert unanswerable
    for question in unanswerable:
        assert question["answerable"] is False
        assert "expected_requirement_ids" not in question
        assert question["question"].strip()
    assert not {q["id"] for q in unanswerable} & {q["id"] for q in questions}
    assert not {q["question"] for q in unanswerable} & {q["question"] for q in questions}


def test_persona_labels_are_not_part_of_the_question_text(questions):
    for question in questions:
        if "persona" in question:
            assert not question["question"].startswith(question["persona"])
            assert "Not answered by the standard" not in question["question"]
