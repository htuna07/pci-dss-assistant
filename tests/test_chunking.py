"""Chunk builder tests: run the chunk CLI on the real extraction output.

Invariants guard against silent text loss and missing citation metadata;
a few values were read by hand from specific records.
"""

import json
import re

import pytest

from conftest import golden_text, run_chunker

STRATEGIES = ("per_record", "grouped", "per_field")
MAX_WORDS = 350
REQUIREMENT_TEXT_FIELDS = (
    "defined_requirement",
    "customized_approach_objective",
    "applicability_notes",
    "testing_procedures",
)
CHUNK_KEYS = {
    "chunk_id",
    "record_type",
    "requirement_id",
    "section_id",
    "group",
    "pdf_pages",
    "document_version",
    "header",
    "text",
}


@pytest.fixture(scope="module")
def records(full_extraction) -> dict[str, dict]:
    return {
        name.removeprefix("requirement-").removesuffix(".json"): json.loads(text)
        for name, text in full_extraction.output_files().items()
    }


@pytest.fixture(scope="module")
def chunks_by_strategy(chunk_runs) -> dict[str, list[dict]]:
    loaded = {}
    for strategy, result in chunk_runs.items():
        assert result.returncode == 0, result.stderr
        path = result.output_dir / f"chunks-{strategy}.jsonl"
        loaded[strategy] = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
    return loaded


def chunk_text_by_requirement(chunks: list[dict]) -> dict[str, str]:
    joined: dict[str, list[str]] = {}
    for chunk in chunks:
        joined.setdefault(chunk["requirement_id"], []).append(chunk["text"])
    return {key: "\n".join(parts) for key, parts in joined.items()}


def source_texts(record: dict) -> list[str]:
    if record["record_type"] == "requirement_introduction":
        texts = [record.get("overview") or "", record.get("category_title") or ""]
        texts += [note["text"] for note in record.get("notes") or []]
        texts += [f"{s['id']} {s['title']}" for s in record.get("sections") or []]
    else:
        texts = [record.get(field) or "" for field in REQUIREMENT_TEXT_FIELDS]
        texts += (record.get("guidance") or {}).values()
    return [text.strip() for text in texts if text.strip()]


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_chunker_succeeds_and_reports_output(chunk_runs, strategy):
    result = chunk_runs[strategy]

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        f"Saved: {result.output_dir / f'chunks-{strategy}.jsonl'}"
    )


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_chunk_has_citation_metadata(chunks_by_strategy, records, strategy):
    for chunk in chunks_by_strategy[strategy]:
        record = records[chunk["requirement_id"]]
        assert set(chunk) == CHUNK_KEYS
        assert chunk["record_type"] == record["record_type"]
        assert chunk["pdf_pages"] == record["pdf_pages"]
        assert chunk["document_version"] == record["document_version"]
        assert chunk["text"].strip()
        assert chunk["header"].startswith(
            f"PCI DSS v{record['document_version']} — Requirement "
            f"{chunk['requirement_id']}"
        )


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_chunk_ids_are_unique(chunks_by_strategy, strategy):
    ids = [chunk["chunk_id"] for chunk in chunks_by_strategy[strategy]]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_record_is_chunked(chunks_by_strategy, records, strategy):
    covered = {chunk["requirement_id"] for chunk in chunks_by_strategy[strategy]}

    assert covered == set(records)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_no_source_text_is_lost(chunks_by_strategy, records, strategy):
    text_by_requirement = chunk_text_by_requirement(chunks_by_strategy[strategy])

    for requirement_id, record in records.items():
        for text in source_texts(record):
            assert text in text_by_requirement[requirement_id], (
                f"{requirement_id}: lost {text[:80]!r}"
            )


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_oversized_chunks_are_exactly_the_logged_unsplittable_fields(
    chunk_runs, chunks_by_strategy, strategy
):
    oversized = [
        chunk
        for chunk in chunks_by_strategy[strategy]
        if len(chunk["text"].split()) > MAX_WORDS
    ]
    warned = re.findall(
        r"WARNING requirement (\S+): .* over the 350-word limit",
        chunk_runs[strategy].stderr,
    )

    assert sorted(chunk["requirement_id"] for chunk in oversized) == sorted(warned)


def test_grouped_strategy_uses_three_groups_per_requirement(chunks_by_strategy):
    groups = {
        chunk["group"]
        for chunk in chunks_by_strategy["grouped"]
        if chunk["record_type"] == "requirement"
    }

    assert groups == {"requirement", "testing", "guidance"}


def test_requirement_groups_are_never_split_at_the_default_limit(chunks_by_strategy):
    split = [
        chunk["chunk_id"]
        for chunk in chunks_by_strategy["grouped"]
        if chunk["group"] in {"requirement", "testing"} and "(part" in chunk["header"]
    ]

    assert split == []


def test_per_record_strategy_keeps_one_group(chunks_by_strategy):
    groups = {
        chunk["group"]
        for chunk in chunks_by_strategy["per_record"]
        if chunk["record_type"] == "requirement"
    }

    assert groups == {"record"}


def test_introductions_are_labelled_and_never_mixed_into_requirement_groups(
    chunks_by_strategy,
):
    introductions = [
        chunk
        for chunk in chunks_by_strategy["grouped"]
        if chunk["record_type"] == "requirement_introduction"
    ]

    assert {chunk["requirement_id"] for chunk in introductions} == {
        str(number) for number in range(1, 13)
    }
    assert {chunk["group"] for chunk in introductions} == {"introduction"}


def test_split_chunks_are_numbered_and_marked_in_header(chunks_by_strategy):
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks_by_strategy["grouped"]}

    assert "4.2.1/guidance/2" in by_id
    assert "(part 2 of" in by_id["4.2.1/guidance/2"]["header"]
    assert "(part" not in by_id["8.4.2/testing/1"]["header"]


def test_hand_checked_requirement_8_4_2(chunks_by_strategy):
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks_by_strategy["grouped"]}
    requirement = by_id["8.4.2/requirement/1"]
    testing = by_id["8.4.2/testing/1"]

    assert "phishing-resistant" in requirement["text"]
    assert "MFA is implemented for all non-console" in requirement["text"]
    assert "8.4.2.b" in testing["text"]
    assert "8.4.2.b" not in requirement["text"]
    assert "Section 8.4: Multi-factor authentication" in requirement["header"]
    assert (
        "Principal requirement 8: Identify Users and Authenticate Access"
        in requirement["header"]
    )
    assert requirement["pdf_pages"] == [203, 204, 205]


def test_grouped_output_matches_golden(chunk_runs):
    result = chunk_runs["grouped"]
    produced = (result.output_dir / "chunks-grouped.jsonl").read_text(encoding="utf-8")
    expected = golden_text("chunks-grouped.jsonl")

    assert produced == expected


def test_max_words_changes_splitting(full_extraction, tmp_path):
    result = run_chunker(
        ["--strategy", "grouped", "--max-words", "100"],
        full_extraction.output_dir,
        tmp_path,
    )
    smaller_limit_count = len(
        (tmp_path / "chunks-grouped.jsonl").read_text(encoding="utf-8").splitlines()
    )
    default_count = len(
        golden_text("chunks-grouped.jsonl").splitlines()
    )

    assert result.returncode == 0
    assert smaller_limit_count > default_count


def test_empty_input_directory_fails_without_output(tmp_path):
    result = run_chunker([], tmp_path / "empty", tmp_path / "out")

    assert result.returncode != 0
    assert not (tmp_path / "out").exists()


def test_unknown_record_type_fails_loudly_and_writes_nothing(
    full_extraction, tmp_path
):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    for name, text in list(full_extraction.output_files().items())[:3]:
        (input_dir / name).write_text(text, encoding="utf-8")
    broken = json.loads(next(iter(full_extraction.output_files().values())))
    broken["record_type"] = "mystery"
    broken["requirement_id"] = "99.9.9"
    (input_dir / "requirement-99.9.9.json").write_text(
        json.dumps(broken), encoding="utf-8"
    )

    result = run_chunker([], input_dir, tmp_path / "out")

    assert result.returncode != 0
    assert "requirement 99.9.9" in result.stderr
    assert not (tmp_path / "out").exists()
