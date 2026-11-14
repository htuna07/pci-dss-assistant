"""Hand-verified expectations for requirements that exercise hard layouts.

Every value was read from the PDF page itself (see `pages`), not copied from
the extractor's output. Text is compared with whitespace collapsed because the
PDF wraps lines.

Quoted passages of the standard live in `tests/golden/sampled_expectations.json`,
which is gitignored because PCI SSC holds the copyright. Without that file the
structural checks (pages, testing procedure IDs, guidance fields) still run and
the text checks are skipped.
"""

import json
import re

import pytest

from conftest import GOLDEN_DIR

LDQUOTE, RDQUOTE, APOSTROPHE = "“", "”", "’"


def norm(text):
    return " ".join(text.split())


def printed_testing_ids(record):
    requirement_id = record["requirement_id"]
    return re.findall(
        rf"(?m)^({re.escape(requirement_id)}(?:\.[a-z])?)\b",
        record["testing_procedures"],
    )


@pytest.fixture(scope="module")
def records(full_extraction):
    assert full_extraction.returncode == 0, full_extraction.stderr
    return {
        json.loads(text)["requirement_id"]: json.loads(text)
        for text in full_extraction.output_files().values()
    }


@pytest.fixture(scope="module")
def text_expectations():
    path = GOLDEN_DIR / "sampled_expectations.json"
    if not path.is_file():
        return {"requirements": {}, "introductions": {}, "shared_guidance_phrase": None}
    return json.loads(path.read_text(encoding="utf-8"))


# Each case: requirement ID -> structural expectations (exact). Keys: pages,
# testing_ids, guidance_keys, has_notes. The matching quoted text (defined,
# objective, notes_*, guidance_*) comes from the local JSON file.
REQUIREMENT_CASES = {
    # Single page, three guidance fields, one unlettered testing procedure.
    "1.1.1": dict(
        pages=[44],
        testing_ids=["1.1.1"],
        guidance_keys=["purpose", "good_practice", "definitions"],
        has_notes=False,
    ),
    # Two requirements share one page; fields must not leak between them.
    "3.7.1": dict(
        pages=[106],
        testing_ids=["3.7.1.a", "3.7.1.b"],
        guidance_keys=["purpose", "further_information"],
        has_notes=False,
    ),
    "3.7.2": dict(
        pages=[106],
        testing_ids=["3.7.2.a", "3.7.2.b"],
        guidance_keys=["purpose"],
        has_notes=False,
    ),
    # Continued with an explicit "(continued)" label; the label printed on
    # page 169 says 7.1.2 but the content is 7.2.1's guidance.
    "7.2.1": dict(
        pages=[168, 169],
        testing_ids=["7.2.1.a", "7.2.1.b"],
        guidance_keys=["purpose", "good_practice", "definitions", "examples"],
        has_notes=False,
    ),
    # Applicability notes on the first page, guidance that continues on the
    # next page together with the start of the following requirement.
    "1.2.3": dict(
        pages=[48, 49],
        testing_ids=["1.2.3.a", "1.2.3.b"],
        guidance_keys=["purpose", "good_practice"],
        has_notes=True,
    ),
    "1.2.4": dict(
        pages=[49, 50],
        testing_ids=["1.2.4.a", "1.2.4.b"],
        guidance_keys=["purpose", "good_practice"],
        has_notes=True,
    ),
    # Three pages: notes on the second, examples and further information on
    # the third, and a continuation page with no heading in the guidance.
    "4.2.1": dict(
        pages=[117, 118, 119],
        testing_ids=["4.2.1.a", "4.2.1.b", "4.2.1.c", "4.2.1.d"],
        guidance_keys=[
            "purpose",
            "good_practice",
            "examples",
            "further_information",
        ],
        has_notes=True,
    ),
    # Four pages with two continuation pages that carry guidance only.
    "6.3.1": dict(
        pages=[147, 148, 149, 150],
        testing_ids=["6.3.1.a", "6.3.1.b"],
        guidance_keys=[
            "purpose",
            "good_practice",
            "examples",
            "further_information",
        ],
        has_notes=True,
    ),
    # Notes continue onto a third page that has no label and no heading.
    "8.4.2": dict(
        pages=[203, 204, 205],
        testing_ids=["8.4.2.a", "8.4.2.b"],
        guidance_keys=["purpose", "definitions"],
        has_notes=True,
    ),
    # Continuation page 233 has no "(continued)" label at all; it begins with
    # 9.5.1's applicability notes and guidance, then 9.5.1.1 starts.
    "9.5.1": dict(
        pages=[232, 233],
        testing_ids=["9.5.1"],
        guidance_keys=["purpose", "good_practice", "further_information"],
        has_notes=True,
    ),
    "9.5.1.1": dict(
        pages=[233, 234],
        testing_ids=["9.5.1.1.a", "9.5.1.1.b", "9.5.1.1.c"],
        guidance_keys=["purpose", "good_practice", "examples"],
        has_notes=False,
    ),
    # Three requirements on one page, the third has no testing text on its
    # own first page, and its objective and testing are on the next page.
    "10.2.1.3": dict(
        pages=[244],
        testing_ids=["10.2.1.3"],
        has_notes=False,
    ),
    "10.2.1.4": dict(
        pages=[244, 245],
        testing_ids=["10.2.1.4"],
        guidance_keys=["purpose"],
        has_notes=False,
    ),
    # "Good Practice" is printed inline after the last line of the Purpose
    # text instead of on its own line.
    "12.3.3": dict(
        pages=[303],
        testing_ids=["12.3.3"],
        guidance_keys=[
            "purpose",
            "good_practice",
            "definitions",
            "further_information",
        ],
        has_notes=True,
    ),
    "12.3.4": dict(
        pages=[304],
        testing_ids=["12.3.4"],
        guidance_keys=["purpose", "good_practice"],
        has_notes=True,
    ),
    # Applicability notes on the middle page, further information spills onto
    # a page that also starts the next requirement.
    "11.4.1": dict(
        pages=[278, 279, 280],
        testing_ids=["11.4.1"],
        guidance_keys=[
            "purpose",
            "good_practice",
            "definitions",
            "further_information",
        ],
        has_notes=True,
    ),
    # Content that continues without a label and without a heading.
    "12.8.2": dict(
        pages=[320, 321],
        testing_ids=["12.8.2.a", "12.8.2.b"],
        guidance_keys=["purpose", "good_practice", "further_information"],
        has_notes=True,
    ),
    # Last requirement of the document, the end of the extraction range.
    "12.10.7": dict(
        pages=[337],
        testing_ids=["12.10.7.a", "12.10.7.b"],
        guidance_keys=["purpose", "good_practice"],
        has_notes=True,
    ),
}


@pytest.mark.parametrize("requirement_id", REQUIREMENT_CASES)
def test_requirement_matches_the_pdf(records, text_expectations, requirement_id):
    expected = {
        **REQUIREMENT_CASES[requirement_id],
        **text_expectations["requirements"].get(requirement_id, {}),
    }
    record = records[requirement_id]

    assert record["pdf_pages"] == expected["pages"]
    assert printed_testing_ids(record) == expected["testing_ids"]
    assert (record["applicability_notes"] is not None) == expected["has_notes"]

    if "guidance_keys" in expected:
        assert list(record["guidance"]) == expected["guidance_keys"]

    if "defined" in expected:
        assert norm(record["defined_requirement"]) == expected["defined"]
    if "defined_start" in expected:
        assert norm(record["defined_requirement"]).startswith(
            expected["defined_start"]
        )
    if "objective" in expected:
        assert norm(record["customized_approach_objective"]) == (
            expected["objective"]
        )
    if "objective_end" in expected:
        assert norm(record["customized_approach_objective"]).endswith(
            expected["objective_end"]
        )

    notes = norm(record["applicability_notes"] or "")
    if "notes_start" in expected:
        assert notes.startswith(expected["notes_start"])
    if "notes_end" in expected:
        assert notes.endswith(expected["notes_end"])
    if "notes_has" in expected:
        assert expected["notes_has"] in notes
    if "notes_lacks" in expected:
        assert expected["notes_lacks"] not in notes

    for name, text in expected.get("guidance", {}).items():
        assert norm(record["guidance"][name]) == text
    for name, text in expected.get("guidance_start", {}).items():
        assert norm(record["guidance"][name]).startswith(text)
    for name, text in expected.get("guidance_end", {}).items():
        assert norm(record["guidance"][name]).endswith(text)
    for name, text in expected.get("guidance_has", {}).items():
        assert text in norm(record["guidance"][name])


def test_mislabeled_continuation_is_not_attributed_to_the_label_requirement(
    records,
):
    # Page 169 is labeled "7.1.2 (continued)" but continues 7.2.1.
    assert 169 not in records["7.1.2"]["pdf_pages"]
    assert "access control model" not in norm(
        json.dumps(records["7.1.2"]["guidance"])
    )


def test_shared_guidance_is_copied_to_11_4_3_and_flagged(records, text_expectations):
    owner, borrower = records["11.4.2"], records["11.4.3"]

    assert owner["pdf_pages"] == [280, 281]
    assert borrower["pdf_pages"] == [281]
    assert norm(owner["defined_requirement"]).startswith(
        "Internal penetration testing is performed:"
    )
    assert norm(borrower["defined_requirement"]).startswith(
        "External penetration testing is performed:"
    )
    assert printed_testing_ids(owner) == ["11.4.2.a", "11.4.2.b"]
    assert printed_testing_ids(borrower) == ["11.4.3.a", "11.4.3.b"]

    assert list(owner["guidance"]) == [
        "purpose",
        "good_practice",
        "further_information",
    ]
    assert borrower["guidance"] == owner["guidance"]
    phrase = text_expectations["shared_guidance_phrase"]
    if phrase:
        assert phrase in norm(owner["guidance"]["purpose"])

    for record in (owner, borrower):
        assert [
            (note["status"], note["pdf_pages"])
            for note in record["extraction_notes"]
        ] == [("provisional", [280, 281])]


def test_requirements_without_exceptions_have_no_extraction_notes(records):
    flagged = sorted(
        requirement_id
        for requirement_id, record in records.items()
        if record.get("extraction_notes")
    )

    assert flagged == ["11.4.2", "11.4.3"]


INTRODUCTION_CASES = {
    # Introduction spanning two pages: sections on the first, overview on
    # the second, with the category title above the requirement title.
    "1": dict(
        pages=[42, 43],
        category="Build and Maintain a Secure Network and Systems",
        title="Install and Maintain Network Security Controls",
        section_ids=["1.1", "1.2", "1.3", "1.4", "1.5"],
        note_count=0,
    ),
    # A requirement that starts a new category has a category title; one
    # that does not, has none.
    "6": dict(
        pages=[138],
        category=None,
        title="Develop and Maintain Secure Systems and Software",
        section_ids=["6.1", "6.2", "6.3", "6.4", "6.5"],
        note_count=1,
    ),
    # Two pages with a note that begins on the second.
    "8": dict(
        pages=[178, 179],
        category=None,
        title="Identify Users and Authenticate Access to System Components",
        section_ids=["8.1", "8.2", "8.3", "8.4", "8.5", "8.6"],
        note_count=1,
        note_pages=[179],
    ),
    # Section titles share a line with their IDs and wrap onto a second one.
    "12": dict(
        pages=[294],
        category="Maintain an Information Security Policy",
        title=(
            "Support Information Security with Organizational Policies "
            "and Programs"
        ),
        section_ids=[f"12.{number}" for number in range(1, 11)],
        note_count=0,
    ),
}


@pytest.mark.parametrize("requirement_id", INTRODUCTION_CASES)
def test_introduction_matches_the_pdf(records, text_expectations, requirement_id):
    expected = {
        **INTRODUCTION_CASES[requirement_id],
        **text_expectations["introductions"].get(requirement_id, {}),
    }
    record = records[requirement_id]

    assert record["record_type"] == "requirement_introduction"
    assert record["pdf_pages"] == expected["pages"]
    assert record["category_title"] == expected["category"]
    assert norm(record["title"]) == expected["title"]
    assert [s["id"] for s in record["sections"]] == expected["section_ids"]
    assert len(record["notes"]) == expected["note_count"]

    if "first_section" in expected:
        assert norm(record["sections"][0]["title"]) == expected["first_section"]
    if "last_section" in expected:
        assert norm(record["sections"][-1]["title"]) == expected["last_section"]

    overview = norm(record["overview"])
    if "overview_start" in expected:
        assert overview.startswith(expected["overview_start"])
    if "overview_end" in expected:
        assert overview.endswith(expected["overview_end"])

    if expected["note_count"]:
        note = record["notes"][0]
        if "note_start" in expected:
            assert norm(note["text"]).startswith(expected["note_start"])
        if "note_pages" in expected:
            assert note["pdf_pages"] == expected["note_pages"]
