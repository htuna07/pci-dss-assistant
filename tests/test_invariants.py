"""Structural checks that hold for any correct extraction.

These catch silent corruption (empty fields, wrong IDs, page drift) that a
golden file updated by mistake would otherwise hide.
"""

import json
import re

import pytest

from conftest import FULL_RANGE

REQUIREMENT_ID = re.compile(r"^\d+(?:\.\d+){2,}$")
TOP_LEVEL_REQUIREMENTS = [str(number) for number in range(1, 13)]


@pytest.fixture(scope="module")
def records(full_extraction):
    return {
        name: json.loads(text)
        for name, text in full_extraction.output_files().items()
    }


@pytest.fixture(scope="module")
def requirements(records):
    return [r for r in records.values() if r["record_type"] == "requirement"]


@pytest.fixture(scope="module")
def introductions(records):
    return [
        r
        for r in records.values()
        if r["record_type"] == "requirement_introduction"
    ]


def test_filename_matches_requirement_id(records):
    for name, record in records.items():
        assert name == f"requirement-{record['requirement_id']}.json"


def test_every_record_has_version_and_pages(records):
    first, last = FULL_RANGE

    for record in records.values():
        assert record["document_version"] == "4.0.1"
        assert record["pdf_pages"] == sorted(set(record["pdf_pages"]))
        assert record["pdf_pages"], record["requirement_id"]
        assert first <= record["pdf_pages"][0]
        assert record["pdf_pages"][-1] <= last


def test_all_twelve_introductions_are_present(introductions):
    assert sorted(
        (i["requirement_id"] for i in introductions), key=int
    ) == TOP_LEVEL_REQUIREMENTS


def test_introductions_are_complete(introductions):
    for intro in introductions:
        assert intro["title"].strip()
        assert intro["overview"].strip()
        assert intro["sections"]

        for section in intro["sections"]:
            assert section["id"].startswith(f"{intro['requirement_id']}.")
            assert section["title"].strip()


def test_requirement_ids_are_wellformed_and_unique(requirements):
    ids = [r["requirement_id"] for r in requirements]

    assert all(REQUIREMENT_ID.match(i) for i in ids)
    assert len(ids) == len(set(ids))


def test_requirements_have_mandatory_text(requirements):
    for record in requirements:
        requirement_id = record["requirement_id"]

        assert record["section_id"] == requirement_id.split(".")[0]
        assert record["defined_requirement"].strip(), requirement_id
        assert record["customized_approach_objective"].strip(), requirement_id
        assert record["testing_procedures"].startswith(requirement_id), (
            requirement_id
        )
        assert not record["defined_requirement"].startswith(requirement_id)


def test_guidance_values_are_non_empty_text(requirements):
    allowed = {
        "purpose",
        "good_practice",
        "definitions",
        "examples",
        "further_information",
    }

    for record in requirements:
        assert set(record["guidance"]) <= allowed
        for key, text in record["guidance"].items():
            assert text.strip(), (record["requirement_id"], key)


def test_every_requirement_belongs_to_an_introduced_section(
    requirements, introductions
):
    section_ids = {
        section["id"] for intro in introductions for section in intro["sections"]
    }

    for record in requirements:
        parent = ".".join(record["requirement_id"].split(".")[:2])
        assert parent in section_ids, record["requirement_id"]


def test_no_requirement_text_contains_layout_markers(requirements):
    for record in requirements:
        for text in (
            record["defined_requirement"],
            record["testing_procedures"],
            *record["guidance"].values(),
        ):
            assert "(continued" not in text.lower(), record["requirement_id"]
