"""Inspect PDF pages or extract requirements across multiple pages."""

import argparse
import json
import re
from pathlib import Path

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = PROJECT_ROOT / "data" / "PCI-DSS-v4_0_1.pdf"

REQUIREMENT_HEADER = "Defined Approach Requirements"
TESTING_HEADER = "Defined Approach Testing Procedures"

# Reviewed continuation-label corrections for this PDF.
# (PDF page number, extracted label ID): actual requirement ID
CONTINUATION_CORRECTIONS = {
    (169, "7.1.2"): "7.2.1",
}

# Supports IDs such as 1.2.3 and 3.5.1.2.
ID_PATTERN = r"\d+(?:\.\d+){2,}"

COLUMN_HEADINGS = {
    "requirement": {
        REQUIREMENT_HEADER: "defined_requirement",
        "Customized Approach Objective": "customized_approach_objective",
        "Applicability Notes": "applicability_notes",
    },
    "testing": {
        TESTING_HEADER: "testing_procedures",
    },
    "guidance": {
        "Purpose": "purpose",
        "Good Practice": "good_practice",
        "Definitions": "definitions",
        "Examples": "examples",
        "Further Information": "further_information",
    },
}

# Expanded to include the text boundaries observed on pages 97–98.
COLUMN_BOUNDS = {
    "requirement": (48, 294),
    "testing": (294, 508),
    "guidance": (508, 744),
}


def read_columns(
    page: pymupdf.Page,
    top: float,
    bottom: float,
) -> dict[str, str]:
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


def field_headed_continuation(columns: dict[str, str]) -> bool:
    def content_lines(text: str) -> list[str]:
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip()
            and line.strip().lower() not in {
                "(continued)",
                "(continued on next page)",
            }
        ]

    left = content_lines(columns["requirement"])
    right = content_lines(columns["guidance"])

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


def find_segments(
    page: pymupdf.Page,
    expecting_continuation: bool = False,
    current_requirement_id: str | None = None,
) -> list[dict]:
    """Split a page into an initial continuation and new tables."""
    table_tops = sorted(
        rect.y0 - 2
        for rect in page.search_for(REQUIREMENT_HEADER)
    )

    # Inspect the area before the first new table.
    # On a continuation-only page, inspect the entire content area.
    initial_bottom = table_tops[0] if table_tops else 535
    initial = (
        read_columns(page, 100, initial_bottom)
        if initial_bottom > 100
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

    correction_key = (page.number + 1, continued_id)
    corrected_id = CONTINUATION_CORRECTIONS.get(correction_key)

    if corrected_id is not None:
        original_id = continued_id

        # Correct the layout label only; preserve the actual content.
        initial["requirement"], count = re.subn(
            rf"(?m)^[ \t]*{re.escape(original_id)}"
            r"\s+\(continued\)[ \t]*$",
            f"{corrected_id} (continued)",
            initial["requirement"],
            count=1,
            flags=re.IGNORECASE,
        )

        if count != 1:
            raise ValueError(
                f"Page {page.number + 1}: expected correction label "
                "was not found"
            )

        continued_id = corrected_id

        print(
            f"Corrected continuation label: PDF page {page.number + 1}, "
            f"{original_id} -> {corrected_id}"
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

    segments = []

    has_initial_content = any(
        text.strip() for text in initial.values()
    )

    if expecting_continuation and not has_initial_content:
        raise ValueError(
            f"Page {page.number + 1}: expected continuation content "
            "before the next requirement"
        )

    if (
        is_continuation
        or (expecting_continuation and has_initial_content)
        or verified_by_testing_id is not None
    ):
        segments.append({
            "continuation": True,
            "continued_id": continued_id,
            "verified_by_testing_id": verified_by_testing_id,
            "columns": initial,
            "verified_by_layout": verified_by_layout,
        })

    for index, top in enumerate(table_tops):
        bottom = (
            table_tops[index + 1]
            if index + 1 < len(table_tops)
            else 535
        )
        segments.append({
            "continuation": False,
            "continued_id": None,
            "columns": read_columns(page, top, bottom),
        })

    if not segments:
        raise ValueError(
            f"Page {page.number + 1}: no supported sections found"
        )

    return segments


def new_record(requirement_id: str) -> dict:
    return {
        "requirement_id": requirement_id,
        "pdf_pages": [],
        "fields": {
            name: {} for name in COLUMN_HEADINGS
        },
        "active": {
            name: None for name in COLUMN_HEADINGS
        },
        "pending": set(),
    }


def consume_column(
    record: dict,
    column: str,
    text: str,
) -> bool:
    """Append content to the active field; switch at headings."""
    headings = COLUMN_HEADINGS[column]
    pending = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.lower() == "(continued on next page)":
            pending = True
            continue

        if line.lower() == "(continued)":
            continue

        explicit = re.fullmatch(
            rf"({ID_PATTERN})\s+\(continued\)",
            line,
            flags=re.IGNORECASE,
        )
        if explicit:
            if explicit.group(1) != record["requirement_id"]:
                raise ValueError("Continuation ID mismatch")
            continue

        # Content after a marker means it is not a trailing marker.
        pending = False

        # Also accept a heading such as "Applicability Notes (continued)".
        heading = re.sub(
            r"\s*\(continued\)$",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()

        if heading in headings:
            key = headings[heading]
            record["active"][column] = key
            record["fields"][column].setdefault(key, [])
            continue

        key = record["active"][column]
        if key is None:
            raise ValueError(
                f"{record['requirement_id']}: text without a heading "
                f"in {column}: {line}"
            )

        record["fields"][column][key].append(line)

    return pending


def finish_record(record: dict) -> dict:

    fields = {
        column: {
            key: "\n".join(lines)
            for key, lines in sections.items()
        }
        for column, sections in record["fields"].items()
    }

    requirement_id = record["requirement_id"]
    left = fields["requirement"]
    testing = fields["testing"].get("testing_procedures", "")

    defined, count = re.subn(
        rf"^{re.escape(requirement_id)}\s+",
        "",
        left.get("defined_requirement", ""),
        count=1,
    )
    if count != 1:
        raise ValueError(
            f"{requirement_id}: missing or mismatched requirement text"
        )

    if not re.match(
        rf"^{re.escape(requirement_id)}(?:\.[a-z]+)?\.?\s+",
        testing,
    ):
        raise ValueError(
            f"{requirement_id}: missing or mismatched testing text; "
            f"PDF pages: {record['pdf_pages']}; "
            f"testing: {testing!r}"
        )

    if not left.get("customized_approach_objective"):
        raise ValueError(
            f"{requirement_id}: missing customized approach objective"
        )

    return {
        "record_type": "requirement",
        "section_id": requirement_id.split(".")[0],
        "document_version": "4.0.1",
        "requirement_id": requirement_id,
        "pdf_pages": record["pdf_pages"],
        "defined_requirement": defined,
        "testing_procedures": testing,
        "customized_approach_objective": left[
            "customized_approach_objective"
        ],
        "applicability_notes": left.get("applicability_notes"),
        "guidance": fields["guidance"],
        "extraction_notes": record.get("extraction_notes", []),
    }


def extract_requirements(
    document: pymupdf.Document,
    start: int,
    end: int,
) -> list[dict]:
    records = {}
    introductions = {}
    current_id = None
    active_introduction = None

    for page_number in range(start, end + 1):
        page = document[page_number - 1]

        has_table = bool(page.search_for(REQUIREMENT_HEADER))
        page_text = read_introduction_text(page)
        intro_id = introduction_id(page_text)

        if intro_id is not None:
            if has_table or page.search_for(TESTING_HEADER):
                raise ValueError(
                    f"Page {page_number}: introduction and table "
                    "on the same page are not supported yet"
                )

            if any(record["pending"] for record in records.values()):
                raise ValueError(
                    f"Page {page_number}: introduction encountered "
                    "while a requirement continuation is pending"
                )

            if intro_id in introductions:
                raise ValueError(
                    f"Duplicate introduction: Requirement {intro_id}"
                )

            record = new_introduction(intro_id)
            introductions[intro_id] = record

            consume_introduction(
                record, page_text, page_number, first_page=True
            )

            active_introduction = intro_id
            current_id = None
            print(
                f"Read introduction: Requirement {intro_id}, "
                f"PDF page {page_number}"
            )
            continue

        if active_introduction is not None:
            if not has_table:
                content_area = pymupdf.Rect(48, 65, 744, 535)

                if (
                    not page_text
                    or page.search_for(
                        TESTING_HEADER,
                        clip=content_area,
                    )
                    or page.search_for(
                        "Requirements and Testing Procedures",
                        clip=content_area,
                    )
                ):
                    raise ValueError(
                        f"Page {page_number}: unsupported introduction "
                        "continuation layout"
                    )

                consume_introduction(
                    introductions[active_introduction],
                    page_text,
                    page_number,
                    first_page=False,
                )

                print(
                    f"Read introduction continuation: "
                    f"Requirement {active_introduction}, "
                    f"PDF page {page_number}"
                )
                continue

            # Confirm that the first table belongs to this introduction.
            first_header = min(
                page.search_for(REQUIREMENT_HEADER),
                key=lambda rect: rect.y0,
            )
            left = read_columns(page, first_header.y0 - 2, 535)[
                "requirement"
            ]
            first_id = re.search(
                rf"^[ \t]*({ID_PATTERN})\s+",
                left,
                flags=re.MULTILINE,
            )

            if (
                first_id is None
                or first_id.group(1).split(".")[0]
                != active_introduction
            ):
                raise ValueError(
                    f"Page {page_number}: first requirement does not "
                    f"match introduction {active_introduction}"
                )

            active_introduction = None

        expecting_continuation = (
            current_id is not None
            and bool(records[current_id]["pending"])
        )

        previous_page_id = (
            current_id
            if (
                current_id is not None
                and records[current_id]["pdf_pages"][-1]
                == page_number - 1
            )
            else None
        )

        for segment in find_segments(
            page,
            expecting_continuation=expecting_continuation,
            current_requirement_id=previous_page_id,
        ):
            columns = segment["columns"]

            if segment["continuation"]:
                requirement_id = segment["continued_id"] or current_id

                if requirement_id not in records:
                    raise ValueError(
                        f"Page {page_number}: continuation without "
                        "its starting requirement"
                    )

                record = records[requirement_id]

                verified_unmarked_continuation = (
                    (
                        segment.get("verified_by_testing_id")
                        == requirement_id
                        or segment.get("verified_by_layout")
                        == requirement_id
                    )
                    and requirement_id == previous_page_id
                )

                if (
                    not record["pending"]
                    and not verified_unmarked_continuation
                ):
                    raise ValueError(
                        f"Page {page_number}: continuation without "
                        f"a preceding continuation marker. "
                        f"Label ID: {segment['continued_id']!r}; "
                        f"selected ID: {requirement_id!r}; "
                        f"active ID: {current_id!r}"
                    )

                if not record["pending"]:
                    evidence = (
                        "reviewed layout"
                        if segment.get("verified_by_layout")
                        else "testing ID"
                    )
                    print(
                        f"Continuation verified by {evidence}: "
                        f"{requirement_id}, PDF page {page_number}"
                    )

                # A continuation may introduce content in another column.
                # Require actual content beyond layout markers.
                has_content = False

                for text in columns.values():
                    for line in text.splitlines():
                        line = line.strip()

                        if not line or re.fullmatch(
                            r"\(continued(?: on next page)?\)",
                            line,
                            flags=re.IGNORECASE,
                        ):
                            continue

                        if re.fullmatch(
                            rf"{ID_PATTERN}\s+\(continued\)",
                            line,
                            flags=re.IGNORECASE,
                        ):
                            continue

                        heading = re.sub(
                            r"\s*\(continued\)$",
                            "",
                            line,
                            flags=re.IGNORECASE,
                        ).strip()

                        if any(
                            heading in headings
                            for headings in COLUMN_HEADINGS.values()
                        ):
                            continue

                        has_content = True
                        break

                    if has_content:
                        break

                if not has_content:
                    raise ValueError(
                        f"Page {page_number}: {requirement_id} "
                        "continuation has no content"
                    )

            else:
                match = re.search(
                    rf"^[ \t]*({ID_PATTERN})\s+",
                    columns["requirement"],
                    flags=re.MULTILINE,
                )
                if not match:
                    raise ValueError(
                        f"Page {page_number}: requirement ID not found. "
                        f"Column text: {columns['requirement']!r}"
                    )

                requirement_id = match.group(1)

                if requirement_id in records:
                    raise ValueError(
                        f"Duplicate requirement start: {requirement_id}"
                    )

                record = new_record(requirement_id)
                records[requirement_id] = record

                # Provisional assumption: all page 281 guidance belongs to 11.4.2.
            if (
                page_number == 281
                and requirement_id == "11.4.3"
                and not segment["continuation"]
            ):
                previous = records.get("11.4.2")
                guidance_text = columns["guidance"].strip()

                if previous is None:
                    raise ValueError(
                        "Page 281: 11.4.2 is required. "
                        "Extend the page range backwards."
                    )

                purpose_text = " ".join(
                    previous["fields"]["guidance"].get("purpose", [])
                )
                guidance_lines = {
                    line.strip()
                    for line in guidance_text.splitlines()
                }

                if (
                    current_id != "11.4.2"
                    or previous["pdf_pages"][-1] != 280
                    or previous["pending"]
                    or previous["active"]["guidance"] != "purpose"
                    or not purpose_text.endswith(
                        "vulnerabilities and misconfigurations that an entity"
                    )
                    or not guidance_text.startswith("did not know about,")
                    or not {"Good Practice", "Further Information"}.issubset(
                        guidance_lines
                    )
                ):
                    raise ValueError(
                        "Page 281: content differs from the provisional "
                        "guidance ownership assumption"
                    )

                continues = consume_column(
                    previous, "guidance", guidance_text
                )
                if continues:
                    previous["pending"].add("guidance")

                previous["pdf_pages"].append(page_number)

                # Copy the complete merged guidance to 11.4.3.
                record["fields"]["guidance"] = {
                    key: list(lines)
                    for key, lines
                    in previous["fields"]["guidance"].items()
                }
                record["active"]["guidance"] = (
                    previous["active"]["guidance"]
                )

                # Already consumed and copied; avoid processing it twice.
                columns["guidance"] = ""

                note = {
                    "pdf_pages": [280, 281],
                    "status": "provisional",
                    "message": (
                        "Complete guidance from 11.4.2 duplicated into "
                        "11.4.3 for retrieval. Includes internal-testing "
                        "wording; reassess after evaluation. This is an "
                        "extraction decision, not confirmed source ownership."
                    ),
                }
                previous.setdefault("extraction_notes", []).append(note)
                record.setdefault("extraction_notes", []).append(note)

                print(
                    "Provisional guidance duplication: "
                    "11.4.2 -> 11.4.3"
                )

            current_id = requirement_id

            if page_number not in record["pdf_pages"]:
                record["pdf_pages"].append(page_number)

            pending = set()
            for column, text in columns.items():
                try:
                    continues = consume_column(record, column, text)
                except ValueError as error:
                    raise ValueError(
                        f"Page {page_number}: {error}"
                    ) from error

                if continues:
                    pending.add(column)

            record["pending"] = pending

    incomplete = [
        requirement_id
        for requirement_id, record in records.items()
        if record["pending"]
    ]
    if incomplete:
        raise ValueError(
            f"Missing continuation pages for: {', '.join(incomplete)}. "
            "Extend the page range."
        )

    if active_introduction is not None:
        raise ValueError(
            f"Range ends within introduction {active_introduction}. "
            "Extend through its first requirement table."
        )

    results = [
        finish_introduction(record)
        for record in introductions.values()
    ]
    results.extend(
        finish_record(record) for record in records.values()
    )

    return results


def read_introduction_text(page: pymupdf.Page) -> str:
    """Read the single-column introduction, excluding the footer."""
    blocks = page.get_text(
        "blocks",
        clip=pymupdf.Rect(48, 65, 744, 535),
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
        raise ValueError("Multiple requirement introduction titles found")

    return matches[0] if matches else None


def new_introduction(requirement_id: str) -> dict:
    return {
        "requirement_id": requirement_id,
        "pdf_pages": [],
        "title_lines": [],
        "sections": [],
        "overview_lines": [],
        "notes": [],
        # Keep the extracted source as well, to aid verification.
        "_mode": "title",
    }


def consume_introduction(
    record: dict,
    text: str,
    page_number: int,
    first_page: bool,
) -> None:
    record["pdf_pages"].append(page_number)

    lines = [
        line.strip() for line in text.splitlines()
        if line.strip()
    ]

    if first_page:
        prefix = (
            rf"^Requirement\s+{re.escape(record['requirement_id'])}"
            r"\s*:\s*"
        )

        title_indexes = [
            index
            for index, line in enumerate(lines)
            if re.match(prefix, line)
        ]

        if len(title_indexes) != 1:
            raise ValueError(
                f"Page {page_number}: introduction title mismatch"
            )

        title_index = title_indexes[0]

        record["category_title"] = (
            " ".join(lines[:title_index]) or None
        )

        lines = lines[title_index:]
        lines[0] = re.sub(prefix, "", lines[0], count=1)

    for line in lines:
        if not line:
            continue

        if line == "Sections":
            record["_mode"] = "sections"
            continue

        if line == "Overview":
            record["_mode"] = "overview"
            continue

        note = re.match(r"^Notes?\s*:\s*(.*)$", line)
        if note:
            record["_mode"] = "notes"
            record["notes"].append({
                "pdf_pages": [page_number],
                "_lines": [],
            })
            if note.group(1):
                record["notes"][-1]["_lines"].append(note.group(1))
            continue

        mode = record["_mode"]

        if mode == "title":
            record["title_lines"].append(line)

        elif mode == "sections":
            section = re.match(
                r"^(\d+\.\d+)(?:\s+(.*))?$",
                line,
            )

            if section:
                section_id = section.group(1)

                if not section_id.startswith(
                    record["requirement_id"] + "."
                ):
                    raise ValueError(
                        f"Page {page_number}: unexpected section "
                        f"{section_id}"
                    )

                record["sections"].append({
                    "id": section_id,
                    "_lines": (
                        [section.group(2)] if section.group(2) else []
                    ),
                })

            elif record["sections"]:
                record["sections"][-1]["_lines"].append(line)

            else:
                raise ValueError(
                    f"Page {page_number}: section title without an ID"
                )

        elif mode == "overview":
            record["overview_lines"].append(line)

        elif mode == "notes":
            current_note = record["notes"][-1]

            if page_number not in current_note["pdf_pages"]:
                current_note["pdf_pages"].append(page_number)

            current_note["_lines"].append(line)


def finish_introduction(record: dict) -> dict:
    if (
        not record["title_lines"]
        or not record["sections"]
        or not record["overview_lines"]
    ):
        raise ValueError(
            f"Requirement {record['requirement_id']}: "
            "incomplete introduction"
        )

    sections = [
        {
            "id": section["id"],
            "title": " ".join(section["_lines"]),
        }
        for section in record["sections"]
    ]

    section_ids = [section["id"] for section in sections]
    if (
        len(section_ids) != len(set(section_ids))
        or any(not section["title"] for section in sections)
    ):
        raise ValueError(
            f"Requirement {record['requirement_id']}: "
            "duplicate or empty sections"
        )

    return {
        "document_version": "4.0.1",
        "record_type": "requirement_introduction",
        "requirement_id": record["requirement_id"],
        "pdf_pages": record["pdf_pages"],
        "title": " ".join(record["title_lines"]),
        "sections": sections,
        "overview": "\n".join(record["overview_lines"]),
        "category_title": record.get("category_title"),
        "notes": [
            {
                "pdf_pages": note["pdf_pages"],
                "text": "\n".join(note["_lines"]),
            }
            for note in record["notes"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--page", type=int)
    selection.add_argument(
        "--pages",
        nargs=2,
        type=int,
        metavar=("START", "END"),
    )

    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--inspect", action="store_true")
    modes.add_argument("--extract", action="store_true")

    args = parser.parse_args()

    if not PDF_PATH.is_file():
        raise SystemExit(f"PDF not found: {PDF_PATH}")

    start, end = (
        (args.page, args.page)
        if args.page is not None
        else args.pages
    )

    with pymupdf.open(PDF_PATH) as document:
        if not 1 <= start <= end <= len(document):
            raise SystemExit(
                f"Page range must be within 1..{len(document)}"
            )

        if args.inspect:
            for page_number in range(start, end + 1):
                page = document[page_number - 1]
                print(f"\n=== PAGE {page_number} ===")

                for block in page.get_text("blocks", sort=True):
                    x0, y0, x1, y1, text, number, kind = block
                    if kind == 0 and text.strip():
                        print(
                            f"\n--- Block {number} "
                            f"x={x0:.1f}..{x1:.1f} "
                            f"y={y0:.1f}..{y1:.1f} ---"
                        )
                        print(text.strip())
            return

        try:
            results = extract_requirements(document, start, end)
        except ValueError as error:
            raise SystemExit(f"Extraction failed: {error}") from error

    # Write only after the entire selected range parses successfully.
    output_dir = PROJECT_ROOT / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    for result in results:
        output_path = (
            output_dir / f"requirement-{result['requirement_id']}.json"
        )
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
