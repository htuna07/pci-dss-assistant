"""Parse the single-column introduction that opens each requirement."""

import re
from dataclasses import dataclass, field

import pymupdf

from config import (
    BODY_BOTTOM,
    BODY_LEFT,
    BODY_RIGHT,
    DOCUMENT_VERSION,
    INTRODUCTION_BODY_TOP,
)
from errors import ExtractionError

INTRODUCTION_BODY = pymupdf.Rect(
    BODY_LEFT, INTRODUCTION_BODY_TOP, BODY_RIGHT, BODY_BOTTOM
)


@dataclass
class SectionDraft:
    id: str
    lines: list[str] = field(default_factory=list)


@dataclass
class NoteDraft:
    pdf_pages: list[int]
    lines: list[str] = field(default_factory=list)


@dataclass
class IntroductionDraft:
    requirement_id: str
    pdf_pages: list[int] = field(default_factory=list)
    title_lines: list[str] = field(default_factory=list)
    sections: list[SectionDraft] = field(default_factory=list)
    overview_lines: list[str] = field(default_factory=list)
    notes: list[NoteDraft] = field(default_factory=list)
    category_title: str | None = None
    mode: str = "title"


def read_introduction_text(page: pymupdf.Page) -> str:
    """Read the single-column introduction, excluding the footer."""
    blocks = page.get_text(
        "blocks",
        clip=INTRODUCTION_BODY,
        sort=True,
    )

    return "\n".join(
        block[4].strip()
        for block in blocks
        if block[6] == 0 and block[4].strip()
    )


def introduction_id(text: str) -> str | None:
    matches = []

    for line in text.splitlines():
        match = re.match(
            r"^Requirement\s+(1[0-2]|[1-9])\s*:",
            line.strip(),
        )
        if match:
            matches.append(match.group(1))

    if len(matches) > 1:
        raise ExtractionError(
            "multiple requirement introduction titles found",
            excerpt=", ".join(f"Requirement {match}" for match in matches),
        )

    return matches[0] if matches else None


def _read_title_block(
    record: IntroductionDraft,
    lines: list[str],
    page_number: int,
) -> list[str]:
    """Split the category title off the first page and strip the prefix."""
    prefix = (
        rf"^Requirement\s+{re.escape(record.requirement_id)}"
        r"\s*:\s*"
    )

    title_indexes = [
        index
        for index, line in enumerate(lines)
        if re.match(prefix, line)
    ]

    if len(title_indexes) != 1:
        raise ExtractionError(
            "introduction title mismatch",
            page=page_number,
            requirement_id=record.requirement_id,
            excerpt="\n".join(lines[:5]),
        )

    title_index = title_indexes[0]
    record.category_title = " ".join(lines[:title_index]) or None

    lines = lines[title_index:]
    lines[0] = re.sub(prefix, "", lines[0], count=1)
    return lines


def _add_section_line(
    record: IntroductionDraft,
    line: str,
    page_number: int,
) -> None:
    section = re.match(r"^(\d+\.\d+)(?:\s+(.*))?$", line)

    if section:
        section_id = section.group(1)

        if not section_id.startswith(record.requirement_id + "."):
            raise ExtractionError(
                f"unexpected section {section_id}",
                page=page_number,
                requirement_id=record.requirement_id,
                excerpt=line,
            )

        record.sections.append(SectionDraft(
            id=section_id,
            lines=[section.group(2)] if section.group(2) else [],
        ))

    elif record.sections:
        record.sections[-1].lines.append(line)

    else:
        raise ExtractionError(
            "section title without an ID",
            page=page_number,
            requirement_id=record.requirement_id,
            excerpt=line,
        )


def consume_introduction(
    record: IntroductionDraft,
    text: str,
    page_number: int,
    first_page: bool,
) -> None:
    record.pdf_pages.append(page_number)

    lines = [
        line.strip() for line in text.splitlines()
        if line.strip()
    ]

    if first_page:
        lines = _read_title_block(record, lines, page_number)

    for line in lines:
        if line == "Sections":
            record.mode = "sections"
            continue

        if line == "Overview":
            record.mode = "overview"
            continue

        note = re.match(r"^Notes?\s*:\s*(.*)$", line)
        if note:
            record.mode = "notes"
            record.notes.append(NoteDraft(pdf_pages=[page_number]))
            if note.group(1):
                record.notes[-1].lines.append(note.group(1))
            continue

        if record.mode == "title":
            record.title_lines.append(line)

        elif record.mode == "sections":
            _add_section_line(record, line, page_number)

        elif record.mode == "overview":
            record.overview_lines.append(line)

        elif record.mode == "notes":
            current_note = record.notes[-1]

            if page_number not in current_note.pdf_pages:
                current_note.pdf_pages.append(page_number)

            current_note.lines.append(line)


def finish_introduction(record: IntroductionDraft) -> dict:
    if (
        not record.title_lines
        or not record.sections
        or not record.overview_lines
    ):
        raise ExtractionError(
            "incomplete introduction: title, sections or overview is empty",
            requirement_id=record.requirement_id,
            pages=record.pdf_pages,
        )

    sections = [
        {
            "id": section.id,
            "title": " ".join(section.lines),
        }
        for section in record.sections
    ]

    section_ids = [section["id"] for section in sections]
    if (
        len(section_ids) != len(set(section_ids))
        or any(not section["title"] for section in sections)
    ):
        raise ExtractionError(
            "duplicate or empty sections",
            requirement_id=record.requirement_id,
            pages=record.pdf_pages,
            excerpt=", ".join(section_ids),
        )

    return {
        "document_version": DOCUMENT_VERSION,
        "record_type": "requirement_introduction",
        "requirement_id": record.requirement_id,
        "pdf_pages": record.pdf_pages,
        "title": " ".join(record.title_lines),
        "sections": sections,
        "overview": "\n".join(record.overview_lines),
        "category_title": record.category_title,
        "notes": [
            {
                "pdf_pages": note.pdf_pages,
                "text": "\n".join(note.lines),
            }
            for note in record.notes
        ],
    }
