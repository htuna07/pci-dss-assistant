"""Turn extracted records into retrieval chunks that keep citation metadata."""

import logging
from dataclasses import asdict, dataclass

from errors import ChunkingError

logger = logging.getLogger("pci_extractor")

STRATEGIES = ("per_record", "grouped", "per_field")

REQUIREMENT_FIELDS = (
    ("defined_requirement", "Defined requirement", "requirement"),
    ("customized_approach_objective", "Customized approach objective", "requirement"),
    ("applicability_notes", "Applicability notes", "requirement"),
    ("testing_procedures", "Testing procedures", "testing"),
)
GUIDANCE_FIELDS = (
    ("purpose", "Purpose"),
    ("good_practice", "Good practice"),
    ("definitions", "Definitions"),
    ("examples", "Examples"),
    ("further_information", "Further information"),
)
GROUP_TITLES = {
    "record": "Full record",
    "requirement": "Requirement",
    "testing": "Testing procedures",
    "guidance": "Guidance",
    "introduction": "Introduction",
}
INTRODUCTION_GROUP = "introduction"


@dataclass(frozen=True)
class Part:
    group: str
    label: str
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    record_type: str
    requirement_id: str
    section_id: str
    group: str
    pdf_pages: list[int]
    document_version: str
    header: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def word_count(text: str) -> int:
    return len(text.split())


def group_for(strategy: str, default_group: str, field_key: str) -> str:
    if strategy == "per_record":
        return "record"
    if strategy == "per_field":
        return field_key
    return default_group


def requirement_parts(record: dict, strategy: str) -> list[Part]:
    parts = []
    for key, label, default_group in REQUIREMENT_FIELDS:
        text = (record.get(key) or "").strip()
        if text:
            parts.append(Part(group_for(strategy, default_group, key), label, text))

    guidance = dict(record.get("guidance") or {})
    for key, label in GUIDANCE_FIELDS:
        text = (guidance.pop(key, None) or "").strip()
        if text:
            parts.append(
                Part(group_for(strategy, "guidance", f"guidance_{key}"), label, text)
            )

    if guidance:
        raise ChunkingError(
            f"unknown guidance keys would be dropped: {sorted(guidance)}",
            requirement_id=record["requirement_id"],
        )
    return parts


def introduction_parts(record: dict) -> list[Part]:
    candidates = [
        ("Category", record.get("category_title") or ""),
        ("Overview", record.get("overview") or ""),
        (
            "Sections",
            "\n".join(f"{s['id']} {s['title']}" for s in record.get("sections") or []),
        ),
        ("Notes", "\n\n".join(n["text"] for n in record.get("notes") or [])),
    ]
    return [
        Part(INTRODUCTION_GROUP, label, text.strip())
        for label, text in candidates
        if text.strip()
    ]


def group_parts(parts: list[Part]) -> dict[str, list[Part]]:
    groups: dict[str, list[Part]] = {}
    for part in parts:
        groups.setdefault(part.group, []).append(part)
    return groups


def pack_parts(parts: list[Part], max_words: int) -> list[list[Part]]:
    """Split only between parts so a field is never cut mid-sentence."""
    pieces: list[list[Part]] = []
    current: list[Part] = []
    current_words = 0
    for part in parts:
        words = word_count(part.text) + word_count(part.label)
        if current and current_words + words > max_words:
            pieces.append(current)
            current, current_words = [], 0
        current.append(part)
        current_words += words
    pieces.append(current)
    return pieces


def render_body(parts: list[Part]) -> str:
    if len(parts) == 1:
        return parts[0].text
    return "\n\n".join(f"{part.label}:\n{part.text}" for part in parts)


def build_header(
    record: dict,
    title: str,
    piece_index: int,
    piece_count: int,
    principal_titles: dict[str, str],
    section_titles: dict[str, str],
) -> str:
    requirement_id = record["requirement_id"]
    is_introduction = record["record_type"] == "requirement_introduction"
    subject = (
        f"Requirement {requirement_id} introduction"
        if is_introduction
        else f"Requirement {requirement_id}"
    )
    suffix = f" (part {piece_index} of {piece_count})" if piece_count > 1 else ""
    first_line = f"PCI DSS v{record['document_version']} — {subject} — {title}{suffix}"

    context = []
    if is_introduction:
        if record.get("title"):
            context.append(record["title"])
    else:
        principal = record["section_id"]
        if principal in principal_titles:
            context.append(f"Principal requirement {principal}: {principal_titles[principal]}")
        section = ".".join(requirement_id.split(".")[:2])
        if section in section_titles:
            context.append(f"Section {section}: {section_titles[section]}")
    return first_line + ("\n" + "; ".join(context) if context else "")


def chunk_record(
    record: dict,
    strategy: str,
    max_words: int,
    principal_titles: dict[str, str],
    section_titles: dict[str, str],
) -> list[Chunk]:
    requirement_id = record["requirement_id"]
    record_type = record["record_type"]
    if record_type == "requirement_introduction":
        parts = introduction_parts(record)
        section_id = requirement_id
    elif record_type == "requirement":
        parts = requirement_parts(record, strategy)
        section_id = record["section_id"]
    else:
        raise ChunkingError(
            f"unknown record_type {record_type!r}", requirement_id=requirement_id
        )
    if not parts:
        raise ChunkingError("record has no text to chunk", requirement_id=requirement_id)

    chunks = []
    for group, group_members in group_parts(parts).items():
        title = GROUP_TITLES.get(group) or group_members[0].label
        pieces = pack_parts(group_members, max_words)
        for index, piece in enumerate(pieces, start=1):
            if len(piece) == 1 and word_count(piece[0].text) > max_words:
                logger.warning(
                    "requirement %s: %r is %d words, over the %d-word limit, "
                    "and cannot be split between parts",
                    requirement_id,
                    piece[0].label,
                    word_count(piece[0].text),
                    max_words,
                )
            chunks.append(
                Chunk(
                    chunk_id=f"{requirement_id}/{group}/{index}",
                    record_type=record_type,
                    requirement_id=requirement_id,
                    section_id=section_id,
                    group=group,
                    pdf_pages=record["pdf_pages"],
                    document_version=record["document_version"],
                    header=build_header(
                        record, title, index, len(pieces), principal_titles, section_titles
                    ),
                    text=render_body(piece),
                )
            )
    return chunks


def build_chunks(records: list[dict], strategy: str, max_words: int) -> list[Chunk]:
    if strategy not in STRATEGIES:
        raise ChunkingError(f"unknown strategy {strategy!r}; choose from {STRATEGIES}")

    principal_titles = {}
    section_titles = {}
    for record in records:
        if record["record_type"] == "requirement_introduction":
            principal_titles[record["requirement_id"]] = record.get("title") or ""
            for section in record.get("sections") or []:
                section_titles[section["id"]] = section["title"]

    chunks = []
    for record in records:
        chunks.extend(
            chunk_record(record, strategy, max_words, principal_titles, section_titles)
        )
    return chunks
