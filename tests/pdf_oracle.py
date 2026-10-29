"""Independent reading of the PDF, used as ground truth for the extractor.

This module deliberately shares no code with `src/`. It identifies structure
from typography only: requirement IDs, testing IDs and field headings are the
bold spans, and the column is decided by the span's x position. Ownership of a
heading comes from the table whose header row sits above it, so the logic is
different from the extractor's segment and continuation handling.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pymupdf

FIRST_PAGE, LAST_PAGE = 42, 337
FOOTER_TOP = 540
REQUIREMENT_COLUMN_END = 294
TESTING_COLUMN_END = 508
TABLE_HEADER_SLACK = 3

ID = r"\d+(?:\.\d+){2,}"
GUIDANCE_HEADINGS = {
    "Purpose": "purpose",
    "Good Practice": "good_practice",
    "Definitions": "definitions",
    "Examples": "examples",
    "Further Information": "further_information",
}
REQUIREMENT_HEADINGS = {
    "Customized Approach Objective": "customized_approach_objective",
    "Applicability Notes": "applicability_notes",
}


@dataclass
class RequirementFacts:
    start_page: int
    testing_ids: list[str] = field(default_factory=list)
    guidance_keys: list[str] = field(default_factory=list)
    requirement_fields: Counter = field(default_factory=Counter)


@dataclass
class _BoldSpan:
    page: int
    x: float
    y: float
    text: str
    line_text: str
    first_in_line: bool


def _bold_spans(page: pymupdf.Page, number: int) -> list[_BoldSpan]:
    spans = []

    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            line_text = "".join(span["text"] for span in line["spans"]).strip()

            for index, span in enumerate(line["spans"]):
                x, y = span["bbox"][0], span["bbox"][1]
                if span["flags"] & 16 and y < FOOTER_TOP and span["text"].strip():
                    spans.append(
                        _BoldSpan(
                            number, x, y, span["text"].strip(), line_text, index == 0
                        )
                    )

    return sorted(spans, key=lambda span: (span.page, span.y, span.x))


def scan_requirements(document: pymupdf.Document) -> dict[str, RequirementFacts]:
    facts: dict[str, RequirementFacts] = {}
    current: str | None = None

    for number in range(FIRST_PAGE, LAST_PAGE + 1):
        page = document[number - 1]
        spans = _bold_spans(page, number)
        tops = sorted(
            rect.y0 for rect in page.search_for("Defined Approach Requirements")
        )

        page_starts = [
            span
            for span in spans
            if span.x < REQUIREMENT_COLUMN_END
            and re.fullmatch(ID, span.text.split()[0])
            and "(continued" not in span.line_text
        ]
        if len(page_starts) != len(tops):
            raise AssertionError(
                f"PDF page {number}: {len(tops)} table headers but "
                f"{len(page_starts)} requirement IDs"
            )

        owners = []
        for span in page_starts:
            requirement_id = span.text.split()[0]
            facts[requirement_id] = RequirementFacts(start_page=number)
            owners.append(requirement_id)

        for span in spans:
            above = [i for i, top in enumerate(tops) if top <= span.y + TABLE_HEADER_SLACK]
            owner = owners[above[-1]] if above else current
            if owner is None:
                continue

            if span.x >= TESTING_COLUMN_END:
                key = GUIDANCE_HEADINGS.get(span.text)
                if key:
                    facts[owner].guidance_keys.append(key)
            elif span.x >= REQUIREMENT_COLUMN_END:
                # The typesetter sometimes splits an ID across fonts
                # ("1." bold + "1.1" regular), so read the whole line.
                match = span.first_in_line and re.match(
                    rf"({ID})(?:\.([a-z]))?\.?(?:\s|$)", span.line_text
                )
                if match:
                    suffix = f".{match.group(2)}" if match.group(2) else ""
                    testing_owner = match.group(1)
                    if testing_owner in facts:
                        facts[testing_owner].testing_ids.append(
                            testing_owner + suffix
                        )
            else:
                key = REQUIREMENT_HEADINGS.get(span.text)
                if key:
                    facts[owner].requirement_fields[key] += 1

        if owners:
            current = owners[-1]

    return facts


@dataclass
class IntroductionFacts:
    page: int
    title: str
    section_ids: list[str]


def scan_introductions(document: pymupdf.Document) -> dict[str, IntroductionFacts]:
    found = {}

    for number in range(FIRST_PAGE, LAST_PAGE + 1):
        page = document[number - 1]
        text = "\n".join(
            block[4].strip()
            for block in page.get_text("blocks", sort=True)
            if block[6] == 0 and block[4].strip() and block[1] < FOOTER_TOP
        )
        match = re.search(r"(?m)^Requirement (\d+): (.+)$", text)
        if not match or "Sections" not in text:
            continue

        requirement = match.group(1)
        block = text.split("Sections", 1)[1].split("Overview", 1)[0]
        section_ids = re.findall(rf"(?m)^({requirement}\.\d+)\b", block)
        found[requirement] = IntroductionFacts(
            page=number,
            title=match.group(2).strip(),
            section_ids=section_ids,
        )

    return found


def group_by_start_page(facts: dict[str, RequirementFacts]) -> dict[int, list[str]]:
    pages = defaultdict(list)
    for requirement_id, item in facts.items():
        pages[item.start_page].append(requirement_id)
    return pages
