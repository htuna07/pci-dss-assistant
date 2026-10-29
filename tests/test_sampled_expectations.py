"""Hand-verified expectations for requirements that exercise hard layouts.

Every value below was read from the PDF page itself (see `pages`), not copied
from the extractor's output. Text is compared with whitespace collapsed
because the PDF wraps lines.
"""

import json
import re

import pytest

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


# Each case: requirement ID -> expectations. Keys:
#   pages, testing_ids, guidance_keys           exact
#   defined, objective                          exact (whitespace-collapsed)
#   defined_start, objective_end, notes_end,
#   guidance_start / guidance_end / guidance_has  {field: text}
REQUIREMENT_CASES = {
    # Single page, three guidance fields, one unlettered testing procedure.
    "1.1.1": dict(
        pages=[44],
        testing_ids=["1.1.1"],
        guidance_keys=["purpose", "good_practice", "definitions"],
        defined_start="All security policies and operational",
        objective_end=f"conform to management{APOSTROPHE}s intent.",
        guidance_end={"definitions": "in accordance with policy objectives."},
        has_notes=False,
    ),
    # Two requirements share one page; fields must not leak between them.
    "3.7.1": dict(
        pages=[106],
        testing_ids=["3.7.1.a", "3.7.1.b"],
        guidance_keys=["purpose", "further_information"],
        defined=(
            "Key-management policies and procedures are implemented to "
            "include generation of strong cryptographic keys used to "
            "protect stored account data."
        ),
        objective="Strong cryptographic keys are generated.",
        guidance={
            "purpose": (
                "Use of strong cryptographic keys significantly increases "
                "the level of security of encrypted account data."
            ),
            "further_information": (
                "See the sources referenced at Cryptographic Key "
                "Generation in Appendix G."
            ),
        },
        has_notes=False,
    ),
    "3.7.2": dict(
        pages=[106],
        testing_ids=["3.7.2.a", "3.7.2.b"],
        guidance_keys=["purpose"],
        defined_start=(
            "Key-management policies and procedures are implemented to "
            "include secure distribution"
        ),
        objective="Cryptographic keys are secured during distribution.",
        guidance_end={"purpose": "are never distributed insecurely."},
        has_notes=False,
    ),
    # Continued with an explicit "(continued)" label; the label printed on
    # page 169 says 7.1.2 but the content is 7.2.1's guidance.
    "7.2.1": dict(
        pages=[168, 169],
        testing_ids=["7.2.1.a", "7.2.1.b"],
        guidance_keys=["purpose", "good_practice", "definitions", "examples"],
        defined_start=(
            "An access control model is defined and includes granting "
            "access as follows:"
        ),
        objective_end="know principles.",
        guidance_start={
            "definitions": "Key elements of an access control model include:",
            "examples": (
                "Access control models that entities can consider include "
                "role-based access control"
            ),
        },
        guidance_end={
            "examples": "depends on their business and access needs."
        },
        has_notes=False,
    ),
    # Applicability notes on the first page, guidance that continues on the
    # next page together with the start of the following requirement.
    "1.2.3": dict(
        pages=[48, 49],
        testing_ids=["1.2.3.a", "1.2.3.b"],
        guidance_keys=["purpose", "good_practice"],
        notes_end="can be used to meet this requirement.",
        notes_lacks="data-flow",
        guidance_end={
            "good_practice": "provide an accurate description of the network."
        },
        has_notes=True,
    ),
    "1.2.4": dict(
        pages=[49, 50],
        testing_ids=["1.2.4.a", "1.2.4.b"],
        guidance_keys=["purpose", "good_practice"],
        notes_start=(
            "A data-flow diagram(s) or other technical or topological "
            "solution"
        ),
        guidance_start={
            "purpose": (
                "An up-to-date, readily available data-flow diagram helps"
            ),
            "good_practice": (
                "The data-flow diagram should include all connection points "
                "where account data is received"
            ),
        },
        guidance_end={"good_practice": "made and approved the updates."},
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
        objective_end="any transmissions over open, public networks.",
        notes_end="and must be fully considered during a PCI DSS assessment.",
        guidance_has={
            "good_practice": "Some protocol implementations (such as SSL"
        },
        guidance_end={"further_information": "Server Certificate Management."},
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
        objective_end="cataloged, and risk assessed.",
        notes_end="risk ranking to be associated with each vulnerability.",
        guidance_end={
            "further_information": "Risk Rating Methodology."
        },
        has_notes=True,
    ),
    # Notes continue onto a third page that has no label and no heading.
    "8.4.2": dict(
        pages=[203, 204, 205],
        testing_ids=["8.4.2.a", "8.4.2.b"],
        guidance_keys=["purpose", "definitions"],
        objective=(
            "Access into the CDE cannot be obtained by the use of a "
            "single authentication factor."
        ),
        notes_has="The MFA requirements apply for all types of system",
        notes_end="fully considered during a PCI DSS assessment.",
        guidance_end={"definitions": f"resistant authentication.{RDQUOTE}"},
        has_notes=True,
    ),
    # Continuation page 233 has no "(continued)" label at all; it begins with
    # 9.5.1's applicability notes and guidance, then 9.5.1.1 starts.
    "9.5.1": dict(
        pages=[232, 233],
        testing_ids=["9.5.1"],
        guidance_keys=["purpose", "good_practice", "further_information"],
        notes_lacks="9.5.1.1",
        has_notes=True,
    ),
    "9.5.1.1": dict(
        pages=[233, 234],
        testing_ids=["9.5.1.1.a", "9.5.1.1.b", "9.5.1.1.c"],
        guidance_keys=["purpose", "good_practice", "examples"],
        objective=(
            "The identity and location of POI devices is recorded and "
            "known at all times."
        ),
        has_notes=False,
    ),
    # Three requirements on one page, the third has no testing text on its
    # own first page, and its objective and testing are on the next page.
    "10.2.1.3": dict(
        pages=[244],
        testing_ids=["10.2.1.3"],
        defined="Audit logs capture all access to audit logs.",
        has_notes=False,
    ),
    "10.2.1.4": dict(
        pages=[244, 245],
        testing_ids=["10.2.1.4"],
        guidance_keys=["purpose"],
        defined="Audit logs capture all invalid logical access attempts.",
        objective="Records of all invalid access attempts are captured.",
        guidance_end={"purpose": "guess a password."},
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
        guidance_end={
            "purpose": "of their cryptographic implementations.",
            "good_practice": (
                "upgrade before the deprecation is impactful to operations."
            ),
        },
        guidance_start={
            "good_practice": (
                "Cryptographic agility is important to ensure an alternative"
            )
        },
        has_notes=True,
    ),
    "12.3.4": dict(
        pages=[304],
        testing_ids=["12.3.4"],
        guidance_keys=["purpose", "good_practice"],
        guidance_end={
            "purpose": "will not be remediated by the vendor or developer.",
            "good_practice": (
                "and/or no longer meet the security needs of the organization."
            ),
        },
        guidance_start={
            "good_practice": "Organizations should review firmware versions"
        },
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
        notes_end="or accessible to public network infrastructures.",
        has_notes=True,
    ),
    # Content that continues without a label and without a heading.
    "12.8.2": dict(
        pages=[320, 321],
        testing_ids=["12.8.2.a", "12.8.2.b"],
        guidance_keys=["purpose", "good_practice", "further_information"],
        notes_end=(
            "evidence not included in a written agreement is not a written "
            "acknowledgment."
        ),
        guidance_end={
            "further_information": "Security Assurance for further guidance."
        },
        has_notes=True,
    ),
    # Last requirement of the document, the end of the extraction range.
    "12.10.7": dict(
        pages=[337],
        testing_ids=["12.10.7.a", "12.10.7.b"],
        guidance_keys=["purpose", "good_practice"],
        notes_end="must be fully considered during a PCI DSS assessment.",
        guidance_end={
            "good_practice": (
                "addressed per this Requirement to prevent recurrence."
            )
        },
        has_notes=True,
    ),
}


@pytest.mark.parametrize("requirement_id", REQUIREMENT_CASES)
def test_requirement_matches_the_pdf(records, requirement_id):
    expected = REQUIREMENT_CASES[requirement_id]
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


def test_shared_guidance_is_copied_to_11_4_3_and_flagged(records):
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
    assert (
        "vulnerabilities and misconfigurations that an entity did not "
        "know about,"
    ) in norm(owner["guidance"]["purpose"])

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
        last_section=(
            "Risks to the CDE from computing devices that are able to "
            "connect to both untrusted networks and the CDE are mitigated."
        ),
        overview_start=(
            "Network security controls (NSCs), such as firewalls and other "
            "network security technologies"
        ),
        overview_end="Refer to Appendix G for definitions of PCI DSS terms.",
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
        note_start=(
            "Requirement 6 applies to all system components, except for "
            "section 6.2"
        ),
    ),
    # Two pages with a note that begins on the second.
    "8": dict(
        pages=[178, 179],
        category=None,
        title="Identify Users and Authenticate Access to System Components",
        section_ids=["8.1", "8.2", "8.3", "8.4", "8.5", "8.6"],
        overview_start=(
            "Two fundamental principles of identifying and authenticating "
            "users"
        ),
        note_count=1,
        note_pages=[179],
        note_start=(
            "Unless otherwise stated in the requirement, these "
            "requirements apply to all accounts"
        ),
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
        first_section=(
            "A comprehensive information security policy that governs and "
            f"provides direction for protection of the entity{APOSTROPHE}s "
            "information assets is known and current."
        ),
        last_section=(
            "Suspected and confirmed security incidents that could impact "
            "the CDE are responded to immediately."
        ),
        overview_end="Refer to Appendix G for definitions of PCI DSS terms.",
        note_count=0,
    ),
}


@pytest.mark.parametrize("requirement_id", INTRODUCTION_CASES)
def test_introduction_matches_the_pdf(records, requirement_id):
    expected = INTRODUCTION_CASES[requirement_id]
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
        assert norm(note["text"]).startswith(expected["note_start"])
        if "note_pages" in expected:
            assert note["pdf_pages"] == expected["note_pages"]
