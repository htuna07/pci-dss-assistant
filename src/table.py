"""Parse the three-column requirement / testing / guidance tables."""

import logging
import re
from dataclasses import dataclass, field

import pymupdf

from config import (
    BODY_BOTTOM,
    COLUMN_BOUNDS,
    COLUMN_HEADINGS,
    CONTINUATION_CORRECTIONS,
    DOCUMENT_VERSION,
    ID_PATTERN,
    REQUIREMENT_HEADER,
    TABLE_BODY_TOP,
    TABLE_HEADER_MARGIN,
)
from errors import ExtractionError

logger = logging.getLogger(__name__)

CONTINUED_ON_NEXT_PAGE = "(continued on next page)"
CONTINUED = "(continued)"
LAYOUT_MARKER = re.compile(
    r"\(continued(?: on next page)?\)",
    flags=re.IGNORECASE,
)
CONTINUED_SUFFIX = re.compile(r"\s*\(continued\)$", flags=re.IGNORECASE)
ID_CONTINUED_LABEL = re.compile(
    rf"{ID_PATTERN}\s+\(continued\)",
    flags=re.IGNORECASE,
)

Columns = dict[str, str]


@dataclass
class Segment:
    """A part of a page that belongs to one requirement table."""

    columns: Columns
    is_continuation: bool = False
    continued_id: str | None = None
    verified_by_testing_id: str | None = None
    verified_by_layout: str | None = None


@dataclass
class RequirementDraft:
    """A requirement being assembled while pages are read."""

    requirement_id: str
    pdf_pages: list[int] = field(default_factory=list)
    fields: dict[str, dict[str, list[str]]] = field(
        default_factory=lambda: {name: {} for name in COLUMN_HEADINGS}
    )
    active: dict[str, str | None] = field(
        default_factory=lambda: {name: None for name in COLUMN_HEADINGS}
    )
    pending: set[str] = field(default_factory=set)
    extraction_notes: list[dict] = field(default_factory=list)


def read_columns(
    page: pymupdf.Page,
    top: float,
    bottom: float,
) -> Columns:
    return {
        name: page.get_text(
            "text",
            clip=pymupdf.Rect(x0, top, x1, bottom),
            sort=True,
        ).strip()
        for name, (x0, x1) in COLUMN_BOUNDS.items()
    }


def continuation_info(text: str) -> tuple[bool, str | None]:
    """Recognize an ID label or a standalone continuation label."""
    explicit = re.search(
        rf"^({ID_PATTERN})\s+\(continued\)\s*$",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    if explicit:
        return True, explicit.group(1)

    standalone = re.search(
        r"^\(continued\)\s*$",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    return standalone is not None, None


def _content_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and line.strip().lower() not in {CONTINUED, CONTINUED_ON_NEXT_PAGE}
    ]


def field_headed_continuation(columns: Columns) -> bool:
    """Detect an unlabeled continuation that opens with a field heading."""
    left = _content_lines(columns["requirement"])
    right = _content_lines(columns["guidance"])

    return bool(
        len(left) > 1
        and left[0] in {
            "Applicability Notes",
            "Customized Approach Objective",
        }
        and not columns["testing"].strip()
        and (
            not right
            or right[0] in COLUMN_HEADINGS["guidance"]
        )
    )


def _apply_continuation_correction(
    page: pymupdf.Page,
    initial: Columns,
    continued_id: str | None,
) -> str | None:
    """Replace a mislabeled continuation ID, keeping the actual content."""
    corrected_id = CONTINUATION_CORRECTIONS.get(
        (page.number + 1, continued_id)
    )
    if corrected_id is None:
        return continued_id

    initial["requirement"], count = re.subn(
        rf"(?m)^[ \t]*{re.escape(continued_id)}"
        r"\s+\(continued\)[ \t]*$",
        f"{corrected_id} (continued)",
        initial["requirement"],
        count=1,
        flags=re.IGNORECASE,
    )

    if count != 1:
        raise ExtractionError(
            "expected correction label was not found",
            page=page.number + 1,
            excerpt=initial["requirement"],
        )

    logger.warning(
        "Corrected continuation label: PDF page %d, %s -> %s",
        page.number + 1,
        continued_id,
        corrected_id,
    )

    return corrected_id


def find_segments(
    page: pymupdf.Page,
    expecting_continuation: bool = False,
    current_requirement_id: str | None = None,
) -> list[Segment]:
    """Split a page into an initial continuation and new tables."""
    table_tops = sorted(
        rect.y0 - TABLE_HEADER_MARGIN
        for rect in page.search_for(REQUIREMENT_HEADER)
    )

    # Inspect the area before the first new table.
    # On a continuation-only page, inspect the entire content area.
    initial_bottom = table_tops[0] if table_tops else BODY_BOTTOM
    initial = (
        read_columns(page, TABLE_BODY_TOP, initial_bottom)
        if initial_bottom > TABLE_BODY_TOP
        else {name: "" for name in COLUMN_BOUNDS}
    )

    is_continuation, continued_id = continuation_info(
        initial["requirement"]
    )

    verified_by_layout = None

    if (
        current_requirement_id is not None
        and field_headed_continuation(initial)
    ):
        is_continuation = True
        continued_id = continued_id or current_requirement_id
        verified_by_layout = current_requirement_id

    continued_id = _apply_continuation_correction(
        page, initial, continued_id
    )

    # A repeated testing ID can identify an unmarked continuation.
    testing_ids = set(re.findall(
        rf"^[ \t]*({ID_PATTERN})(?:\.[a-z]+)?(?=\s)",
        initial["testing"],
        flags=re.MULTILINE,
    ))

    verified_by_testing_id = (
        current_requirement_id
        if (
            current_requirement_id is not None
            and testing_ids == {current_requirement_id}
        )
        else None
    )

    has_initial_content = any(
        text.strip() for text in initial.values()
    )

    if expecting_continuation and not has_initial_content:
        raise ExtractionError(
            "expected continuation content before the next requirement",
            page=page.number + 1,
        )

    segments = []

    if (
        is_continuation
        or (expecting_continuation and has_initial_content)
        or verified_by_testing_id is not None
    ):
        segments.append(Segment(
            columns=initial,
            is_continuation=True,
            continued_id=continued_id,
            verified_by_testing_id=verified_by_testing_id,
            verified_by_layout=verified_by_layout,
        ))

    for index, top in enumerate(table_tops):
        bottom = (
            table_tops[index + 1]
            if index + 1 < len(table_tops)
            else BODY_BOTTOM
        )
        segments.append(Segment(columns=read_columns(page, top, bottom)))

    if not segments:
        raise ExtractionError(
            "no supported sections found",
            page=page.number + 1,
        )

    return segments


def has_substantive_content(columns: Columns) -> bool:
    """Tell real continuation content apart from layout markers."""
    for text in columns.values():
        for raw_line in text.splitlines():
            line = raw_line.strip()

            if not line or LAYOUT_MARKER.fullmatch(line):
                continue

            if ID_CONTINUED_LABEL.fullmatch(line):
                continue

            heading = CONTINUED_SUFFIX.sub("", line).strip()
            if any(
                heading in headings
                for headings in COLUMN_HEADINGS.values()
            ):
                continue

            return True

    return False


def split_inline_heading(line: str, headings: dict[str, str]) -> list[str]:
    """Separate a heading typeset at the end of a paragraph's last line.

    The PDF sometimes prints "... implementations. Good Practice" on one line.
    Requiring sentence-ending punctuation before the heading keeps prose that
    merely ends with a heading word intact.
    """
    names = "|".join(re.escape(name) for name in headings)
    match = re.fullmatch(rf"(.*[.!?])\s+({names})", line)
    if match is None:
        return [line]

    logger.debug("Split inline heading %r from %r", match.group(2), line)
    return [match.group(1), match.group(2)]


def consume_column(
    record: RequirementDraft,
    column: str,
    text: str,
) -> bool:
    """Append content to the active field; switch at headings.

    Returns True when the column ends with a "continued on next page" marker.
    """
    headings = COLUMN_HEADINGS[column]
    pending = False

    lines = [
        part
        for raw_line in text.splitlines()
        if raw_line.strip()
        for part in split_inline_heading(raw_line.strip(), headings)
    ]

    for line in lines:
        if line.lower() == CONTINUED_ON_NEXT_PAGE:
            pending = True
            continue

        if line.lower() == CONTINUED:
            continue

        explicit = re.fullmatch(
            rf"({ID_PATTERN})\s+\(continued\)",
            line,
            flags=re.IGNORECASE,
        )
        if explicit:
            if explicit.group(1) != record.requirement_id:
                raise ExtractionError(
                    f"continuation label {explicit.group(1)} does not "
                    "match the requirement being read",
                    requirement_id=record.requirement_id,
                    column=column,
                    excerpt=line,
                )
            continue

        # Content after a marker means it is not a trailing marker.
        pending = False

        # Also accept a heading such as "Applicability Notes (continued)".
        heading = CONTINUED_SUFFIX.sub("", line).strip()

        if heading in headings:
            key = headings[heading]
            logger.debug(
                "%s %s column: field %s starts",
                record.requirement_id,
                column,
                key,
            )
            record.active[column] = key
            record.fields[column].setdefault(key, [])
            continue

        key = record.active[column]
        if key is None:
            raise ExtractionError(
                "text without a heading",
                requirement_id=record.requirement_id,
                column=column,
                excerpt=line,
            )

        record.fields[column][key].append(line)

    return pending


def finish_record(record: RequirementDraft) -> dict:
    fields = {
        column: {
            key: "\n".join(lines)
            for key, lines in sections.items()
        }
        for column, sections in record.fields.items()
    }

    requirement_id = record.requirement_id
    left = fields["requirement"]
    testing = fields["testing"].get("testing_procedures", "")

    defined, count = re.subn(
        rf"^{re.escape(requirement_id)}\s+",
        "",
        left.get("defined_requirement", ""),
        count=1,
    )
    if count != 1:
        raise ExtractionError(
            "missing or mismatched requirement text",
            requirement_id=requirement_id,
            pages=record.pdf_pages,
            column="requirement",
            excerpt=left.get("defined_requirement", ""),
        )

    if not re.match(
        rf"^{re.escape(requirement_id)}(?:\.[a-z]+)?\.?\s+",
        testing,
    ):
        raise ExtractionError(
            "missing or mismatched testing text",
            requirement_id=requirement_id,
            pages=record.pdf_pages,
            column="testing",
            excerpt=testing,
        )

    if not left.get("customized_approach_objective"):
        raise ExtractionError(
            "missing customized approach objective",
            requirement_id=requirement_id,
            pages=record.pdf_pages,
            column="requirement",
        )

    return {
        "record_type": "requirement",
        "section_id": requirement_id.split(".")[0],
        "document_version": DOCUMENT_VERSION,
        "requirement_id": requirement_id,
        "pdf_pages": record.pdf_pages,
        "defined_requirement": defined,
        "testing_procedures": testing,
        "customized_approach_objective": left[
            "customized_approach_objective"
        ],
        "applicability_notes": left.get("applicability_notes"),
        "guidance": fields["guidance"],
        "extraction_notes": record.extraction_notes,
    }
