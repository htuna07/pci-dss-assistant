"""Check every extracted record against an independent reading of the PDF.

Unlike the golden-master tests, these fail when the extractor is wrong even
if it has always been wrong: the expected values come from `pdf_oracle`, which
reads the PDF by typography instead of reusing the extractor's logic.
"""

import json
import re

import pymupdf
import pytest

from conftest import PDF_PATH
from pdf_oracle import (
    FIRST_PAGE,
    LAST_PAGE,
    scan_introductions,
    scan_requirements,
)

# The PDF prints one guidance cell for 11.4.2 and 11.4.3 together. The
# extractor gives the complete cell to both requirements on purpose.
SHARED_GUIDANCE = ("11.4.2", "11.4.3")

# The PDF prints "Good Practice" at the end of the last Purpose line instead
# of on its own line, and the extractor only recognizes headings that are a
# whole line. Their good-practice text is currently merged into `purpose`.
INLINE_HEADING_BUGS = ("12.3.3", "12.3.4")

LAYOUT_RESIDUE = [
    "Defined Approach Requirements",
    "Defined Approach Testing Procedures",
    "(continued on next page)",
    "PCI Security Standards Council, LLC",
    "Payment Card Industry Data Security Standard: Requirements",
]


@pytest.fixture(scope="module")
def document():
    with pymupdf.open(PDF_PATH) as opened:
        yield opened


@pytest.fixture(scope="module")
def facts(document):
    return scan_requirements(document)


@pytest.fixture(scope="module")
def intro_facts(document):
    return scan_introductions(document)


@pytest.fixture(scope="module")
def records(full_extraction):
    assert full_extraction.returncode == 0, full_extraction.stderr
    return {
        text_name: json.loads(text)
        for text_name, text in full_extraction.output_files().items()
    }


@pytest.fixture(scope="module")
def requirements(records):
    return {
        r["requirement_id"]: r
        for r in records.values()
        if r["record_type"] == "requirement"
    }


@pytest.fixture(scope="module")
def introductions(records):
    return {
        r["requirement_id"]: r
        for r in records.values()
        if r["record_type"] == "requirement_introduction"
    }


def expected_guidance_keys(facts, requirement_id):
    if requirement_id in SHARED_GUIDANCE:
        return [
            key
            for shared_id in SHARED_GUIDANCE
            for key in facts[shared_id].guidance_keys
        ]
    return facts[requirement_id].guidance_keys


def test_same_requirements_as_the_pdf(facts, requirements):
    assert sorted(set(facts) - set(requirements)) == []
    assert sorted(set(requirements) - set(facts)) == []
    assert len(facts) == 250


def test_every_requirement_starts_on_its_pdf_page(facts, requirements):
    wrong = {
        requirement_id: (facts[requirement_id].start_page, record["pdf_pages"][0])
        for requirement_id, record in requirements.items()
        if record["pdf_pages"][0] != facts[requirement_id].start_page
    }

    assert wrong == {}, "requirement: (PDF start page, extracted start page)"


def test_requirement_pages_are_consecutive(requirements):
    for requirement_id, record in requirements.items():
        pages = record["pdf_pages"]
        assert pages == list(range(pages[0], pages[-1] + 1)), requirement_id


def test_testing_procedures_have_the_ids_printed_in_the_pdf(facts, requirements):
    wrong = {}

    for requirement_id, record in requirements.items():
        extracted = re.findall(
            rf"(?m)^({re.escape(requirement_id)}(?:\.[a-z])?)\b",
            record["testing_procedures"],
        )
        if extracted != facts[requirement_id].testing_ids:
            wrong[requirement_id] = (facts[requirement_id].testing_ids, extracted)

    assert wrong == {}, "requirement: (PDF testing IDs, extracted testing IDs)"


def test_guidance_fields_match_the_headings_in_the_pdf(facts, requirements):
    wrong = {}

    for requirement_id, record in requirements.items():
        if requirement_id in INLINE_HEADING_BUGS:
            continue

        expected = expected_guidance_keys(facts, requirement_id)
        if list(record["guidance"]) != expected:
            wrong[requirement_id] = (expected, list(record["guidance"]))

    assert wrong == {}, "requirement: (PDF headings, extracted fields)"


@pytest.mark.xfail(
    strict=True,
    reason="heading printed inline after the Purpose text is not recognized",
)
@pytest.mark.parametrize("requirement_id", INLINE_HEADING_BUGS)
def test_inline_good_practice_heading_is_recognized(
    facts, requirements, requirement_id
):
    record = requirements[requirement_id]

    assert list(record["guidance"]) == facts[requirement_id].guidance_keys
    assert "Good Practice" not in record["guidance"]["purpose"]


def test_requirement_fields_match_the_headings_in_the_pdf(facts, requirements):
    wrong = {}

    for requirement_id, record in requirements.items():
        printed = facts[requirement_id].requirement_fields
        expected = (printed["customized_approach_objective"], printed["applicability_notes"])
        actual = (
            1 if record["customized_approach_objective"] else 0,
            1 if record["applicability_notes"] else 0,
        )
        if actual != expected:
            wrong[requirement_id] = (expected, actual)

    assert wrong == {}, "requirement: ((objective, notes) in PDF, extracted)"


def test_every_pdf_page_is_used_by_some_record(records):
    used = {page for record in records.values() for page in record["pdf_pages"]}

    assert sorted(set(range(FIRST_PAGE, LAST_PAGE + 1)) - used) == []


def test_introductions_match_the_pdf(intro_facts, introductions):
    assert sorted(intro_facts, key=int) == sorted(introductions, key=int)

    for requirement, printed in intro_facts.items():
        record = introductions[requirement]
        assert record["pdf_pages"][0] == printed.page, requirement
        assert " ".join(record["title"].split()).startswith(printed.title), requirement
        assert [s["id"] for s in record["sections"]] == printed.section_ids, requirement


def test_no_layout_residue_in_any_text_field(records):
    def texts(record):
        for value in record.values():
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                yield from (v for v in value.values() if isinstance(v, str))

    for record in records.values():
        for text in texts(record):
            for residue in LAYOUT_RESIDUE:
                assert residue not in text, (record["requirement_id"], residue)
