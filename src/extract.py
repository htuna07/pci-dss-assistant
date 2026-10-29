"""Walk a page range and assemble requirement and introduction records."""

import re
from dataclasses import dataclass, field

import pymupdf

from config import (
    BODY_BOTTOM,
    ID_PATTERN,
    REQUIREMENT_HEADER,
    RUNNING_TITLE,
    TABLE_HEADER_MARGIN,
    TESTING_HEADER,
)
from introduction import (
    INTRODUCTION_BODY,
    IntroductionDraft,
    consume_introduction,
    finish_introduction,
    introduction_id,
    read_introduction_text,
)
from table import (
    RequirementDraft,
    Segment,
    consume_column,
    finish_record,
    find_segments,
    has_substantive_content,
    read_columns,
)

# The guidance printed on page 281 starts in 11.4.2 and is shared by 11.4.3.
# The PDF gives no label to tell which requirement owns it, so the owner was
# assumed from the layout and the assumption is re-verified on every run.
SHARED_GUIDANCE_PAGE = 281
SHARED_GUIDANCE_OWNER = "11.4.2"
SHARED_GUIDANCE_BORROWER = "11.4.3"
SHARED_GUIDANCE_OWNER_LAST_PAGE = 280
SHARED_GUIDANCE_OWNER_TAIL = (
    "vulnerabilities and misconfigurations that an entity"
)
SHARED_GUIDANCE_HEAD = "did not know about,"


@dataclass
class ExtractionState:
    records: dict[str, RequirementDraft] = field(default_factory=dict)
    introductions: dict[str, IntroductionDraft] = field(default_factory=dict)
    current_id: str | None = None
    active_introduction: str | None = None


def extract_requirements(
    document: pymupdf.Document,
    start: int,
    end: int,
) -> list[dict]:
    state = ExtractionState()

    for page_number in range(start, end + 1):
        read_page(state, document[page_number - 1], page_number)

    ensure_range_is_complete(state)

    results = [
        finish_introduction(record)
        for record in state.introductions.values()
    ]
    results.extend(
        finish_record(record) for record in state.records.values()
    )
    return results


def read_page(
    state: ExtractionState,
    page: pymupdf.Page,
    page_number: int,
) -> None:
    has_table = bool(page.search_for(REQUIREMENT_HEADER))
    page_text = read_introduction_text(page)
    intro_id = introduction_id(page_text)

    if intro_id is not None:
        start_introduction(
            state, page, page_number, has_table, page_text, intro_id
        )
        return

    if state.active_introduction is not None:
        if not has_table:
            continue_introduction(state, page, page_number, page_text)
            return

        ensure_first_table_matches_introduction(state, page, page_number)
        state.active_introduction = None

    read_tables(state, page, page_number)


def start_introduction(
    state: ExtractionState,
    page: pymupdf.Page,
    page_number: int,
    has_table: bool,
    page_text: str,
    intro_id: str,
) -> None:
    if has_table or page.search_for(TESTING_HEADER):
        raise ValueError(
            f"Page {page_number}: introduction and table "
            "on the same page are not supported yet"
        )

    if any(record.pending for record in state.records.values()):
        raise ValueError(
            f"Page {page_number}: introduction encountered "
            "while a requirement continuation is pending"
        )

    if intro_id in state.introductions:
        raise ValueError(f"Duplicate introduction: Requirement {intro_id}")

    record = IntroductionDraft(requirement_id=intro_id)
    state.introductions[intro_id] = record

    consume_introduction(record, page_text, page_number, first_page=True)

    state.active_introduction = intro_id
    state.current_id = None
    print(
        f"Read introduction: Requirement {intro_id}, "
        f"PDF page {page_number}"
    )


def continue_introduction(
    state: ExtractionState,
    page: pymupdf.Page,
    page_number: int,
    page_text: str,
) -> None:
    if (
        not page_text
        or page.search_for(TESTING_HEADER, clip=INTRODUCTION_BODY)
        or page.search_for(RUNNING_TITLE, clip=INTRODUCTION_BODY)
    ):
        raise ValueError(
            f"Page {page_number}: unsupported introduction "
            "continuation layout"
        )

    consume_introduction(
        state.introductions[state.active_introduction],
        page_text,
        page_number,
        first_page=False,
    )

    print(
        f"Read introduction continuation: "
        f"Requirement {state.active_introduction}, "
        f"PDF page {page_number}"
    )


def ensure_first_table_matches_introduction(
    state: ExtractionState,
    page: pymupdf.Page,
    page_number: int,
) -> None:
    first_header = min(
        page.search_for(REQUIREMENT_HEADER),
        key=lambda rect: rect.y0,
    )
    left = read_columns(
        page, first_header.y0 - TABLE_HEADER_MARGIN, BODY_BOTTOM
    )["requirement"]
    first_id = re.search(
        rf"^[ \t]*({ID_PATTERN})\s+",
        left,
        flags=re.MULTILINE,
    )

    if (
        first_id is None
        or first_id.group(1).split(".")[0] != state.active_introduction
    ):
        raise ValueError(
            f"Page {page_number}: first requirement does not "
            f"match introduction {state.active_introduction}"
        )


def read_tables(
    state: ExtractionState,
    page: pymupdf.Page,
    page_number: int,
) -> None:
    current = (
        state.records[state.current_id]
        if state.current_id is not None
        else None
    )
    expecting_continuation = current is not None and bool(current.pending)
    previous_page_id = (
        state.current_id
        if current is not None and current.pdf_pages[-1] == page_number - 1
        else None
    )

    for segment in find_segments(
        page,
        expecting_continuation=expecting_continuation,
        current_requirement_id=previous_page_id,
    ):
        if segment.is_continuation:
            record = continue_record(
                state, segment, page_number, previous_page_id
            )
        else:
            record = start_record(state, segment, page_number)

            if (
                page_number == SHARED_GUIDANCE_PAGE
                and record.requirement_id == SHARED_GUIDANCE_BORROWER
            ):
                share_guidance(state, record, segment, page_number)

        state.current_id = record.requirement_id

        if page_number not in record.pdf_pages:
            record.pdf_pages.append(page_number)

        record.pending = consume_segment(record, segment, page_number)


def continue_record(
    state: ExtractionState,
    segment: Segment,
    page_number: int,
    previous_page_id: str | None,
) -> RequirementDraft:
    requirement_id = segment.continued_id or state.current_id

    if requirement_id not in state.records:
        raise ValueError(
            f"Page {page_number}: continuation without "
            "its starting requirement"
        )

    record = state.records[requirement_id]

    verified_unmarked_continuation = (
        (
            segment.verified_by_testing_id == requirement_id
            or segment.verified_by_layout == requirement_id
        )
        and requirement_id == previous_page_id
    )

    if not record.pending and not verified_unmarked_continuation:
        raise ValueError(
            f"Page {page_number}: continuation without "
            f"a preceding continuation marker. "
            f"Label ID: {segment.continued_id!r}; "
            f"selected ID: {requirement_id!r}; "
            f"active ID: {state.current_id!r}"
        )

    if not record.pending:
        evidence = (
            "reviewed layout"
            if segment.verified_by_layout
            else "testing ID"
        )
        print(
            f"Continuation verified by {evidence}: "
            f"{requirement_id}, PDF page {page_number}"
        )

    # A continuation may introduce content in another column, so require
    # actual content beyond layout markers.
    if not has_substantive_content(segment.columns):
        raise ValueError(
            f"Page {page_number}: {requirement_id} "
            "continuation has no content"
        )

    return record


def start_record(
    state: ExtractionState,
    segment: Segment,
    page_number: int,
) -> RequirementDraft:
    requirement_column = segment.columns["requirement"]
    match = re.search(
        rf"^[ \t]*({ID_PATTERN})\s+",
        requirement_column,
        flags=re.MULTILINE,
    )
    if not match:
        raise ValueError(
            f"Page {page_number}: requirement ID not found. "
            f"Column text: {requirement_column!r}"
        )

    requirement_id = match.group(1)

    if requirement_id in state.records:
        raise ValueError(f"Duplicate requirement start: {requirement_id}")

    record = RequirementDraft(requirement_id=requirement_id)
    state.records[requirement_id] = record
    return record


def consume_segment(
    record: RequirementDraft,
    segment: Segment,
    page_number: int,
) -> set[str]:
    """Feed every column of a segment; return columns that continue."""
    pending = set()

    for column, text in segment.columns.items():
        try:
            continues = consume_column(record, column, text)
        except ValueError as error:
            raise ValueError(f"Page {page_number}: {error}") from error

        if continues:
            pending.add(column)

    return pending


def share_guidance(
    state: ExtractionState,
    borrower: RequirementDraft,
    segment: Segment,
    page_number: int,
) -> None:
    """Give the borrower the owner's complete guidance, including page 281."""
    owner = state.records.get(SHARED_GUIDANCE_OWNER)
    guidance_text = segment.columns["guidance"].strip()

    if owner is None:
        raise ValueError(
            f"Page {page_number}: {SHARED_GUIDANCE_OWNER} is required. "
            "Extend the page range backwards."
        )

    purpose_text = " ".join(owner.fields["guidance"].get("purpose", []))
    guidance_lines = {
        line.strip() for line in guidance_text.splitlines()
    }

    if (
        state.current_id != SHARED_GUIDANCE_OWNER
        or owner.pdf_pages[-1] != SHARED_GUIDANCE_OWNER_LAST_PAGE
        or owner.pending
        or owner.active["guidance"] != "purpose"
        or not purpose_text.endswith(SHARED_GUIDANCE_OWNER_TAIL)
        or not guidance_text.startswith(SHARED_GUIDANCE_HEAD)
        or not {"Good Practice", "Further Information"}.issubset(
            guidance_lines
        )
    ):
        raise ValueError(
            f"Page {page_number}: content differs from the provisional "
            "guidance ownership assumption"
        )

    if consume_column(owner, "guidance", guidance_text):
        owner.pending.add("guidance")

    owner.pdf_pages.append(page_number)

    borrower.fields["guidance"] = {
        key: list(lines) for key, lines in owner.fields["guidance"].items()
    }
    borrower.active["guidance"] = owner.active["guidance"]

    # Already consumed and copied; avoid processing it twice.
    segment.columns["guidance"] = ""

    note = {
        "pdf_pages": [SHARED_GUIDANCE_OWNER_LAST_PAGE, page_number],
        "status": "provisional",
        "message": (
            f"Complete guidance from {SHARED_GUIDANCE_OWNER} duplicated into "
            f"{SHARED_GUIDANCE_BORROWER} for retrieval. Includes "
            "internal-testing wording; reassess after evaluation. This is an "
            "extraction decision, not confirmed source ownership."
        ),
    }
    owner.extraction_notes.append(note)
    borrower.extraction_notes.append(note)

    print(
        "Provisional guidance duplication: "
        f"{SHARED_GUIDANCE_OWNER} -> {SHARED_GUIDANCE_BORROWER}"
    )


def ensure_range_is_complete(state: ExtractionState) -> None:
    incomplete = [
        requirement_id
        for requirement_id, record in state.records.items()
        if record.pending
    ]
    if incomplete:
        raise ValueError(
            f"Missing continuation pages for: {', '.join(incomplete)}. "
            "Extend the page range."
        )

    if state.active_introduction is not None:
        raise ValueError(
            f"Range ends within introduction {state.active_introduction}. "
            "Extend through its first requirement table."
        )
