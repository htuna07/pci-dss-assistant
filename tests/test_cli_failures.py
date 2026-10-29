"""Unsupported ranges must fail with a clear message and write nothing."""

import pytest

from conftest import GOLDEN_DIR, run_cli

FAILURE_CASES = [
    pytest.param(
        ["--page", "1", "--extract"],
        "Extraction failed: PDF page 1: no supported sections found",
        1,
        id="front-matter-page",
    ),
    pytest.param(
        ["--pages", "43", "50", "--extract"],
        "Extraction failed: PDF page 43: no supported sections found",
        43,
        id="starts-on-introduction-continuation",
    ),
    pytest.param(
        ["--pages", "279", "281", "--extract"],
        "Extraction failed: PDF page 279: no supported sections found",
        279,
        id="starts-on-non-requirement-page",
    ),
    pytest.param(
        ["--pages", "281", "285", "--extract"],
        "Extraction failed: PDF page 281, requirement 11.4.3: "
        "11.4.2 is required. Extend the page range backwards.",
        281,
        id="missing-previous-requirement",
    ),
    pytest.param(
        ["--pages", "330", "340", "--extract"],
        "Extraction failed: PDF page 330, requirement 12.9.2: "
        "continuation without its starting requirement "
        "(label ID: '12.9.2', active ID: None)",
        330,
        id="continuation-without-start",
    ),
]

INCOMPLETE_RANGE_CASES = [
    pytest.param(
        ["--page", "48", "--extract"],
        "Extraction failed: Missing continuation pages for: "
        "1.2.3 (last page read: 48). Extend the page range.",
        id="ends-before-continuation",
    ),
    pytest.param(
        ["--page", "42", "--extract"],
        "Extraction failed: requirement 1: range ends within the "
        "introduction. Extend through its first requirement table.",
        id="ends-within-introduction",
    ),
]

RANGE_ERROR_CASES = [
    pytest.param(["--page", "0", "--extract"], id="page-below-range"),
    pytest.param(["--page", "398", "--extract"], id="page-above-range"),
    pytest.param(["--pages", "5", "3", "--extract"], id="reversed-range"),
]


@pytest.mark.parametrize(("args", "message", "page"), FAILURE_CASES)
def test_failure_names_location_and_writes_nothing(
    tmp_path, args, message, page
):
    output_dir = tmp_path / "out"

    result = run_cli(args, output_dir)

    assert result.returncode == 1
    assert message in result.stderr
    assert (
        f"python src/main.py --page {page} --inspect" in result.stderr
    )
    assert "Traceback" not in result.stderr
    assert not output_dir.exists()


@pytest.mark.parametrize(("args", "message"), INCOMPLETE_RANGE_CASES)
def test_incomplete_range_is_rejected_without_output(tmp_path, args, message):
    output_dir = tmp_path / "out"

    result = run_cli(args, output_dir)

    assert result.returncode == 1
    assert message in result.stderr
    assert not output_dir.exists()


def test_verbose_failure_shows_traceback(tmp_path):
    result = run_cli(["--page", "1", "--extract", "--verbose"], tmp_path / "o")

    assert result.returncode == 1
    assert "Traceback" in result.stderr
    assert "ExtractionError" in result.stderr


@pytest.mark.parametrize("args", RANGE_ERROR_CASES)
def test_range_outside_document_is_rejected(tmp_path, args):
    output_dir = tmp_path / "out"

    result = run_cli(args, output_dir)

    assert result.returncode == 1
    assert result.stderr.strip().endswith("Page range must be within 1..397")
    assert not output_dir.exists()


def test_partial_range_matches_full_extraction(tmp_path):
    result = run_cli(["--pages", "168", "170", "--extract"], tmp_path / "out")

    assert result.returncode == 0, result.stderr
    assert (
        "WARNING Corrected continuation label: PDF page 169, 7.1.2 -> 7.2.1"
        in result.stderr
    )

    produced = result.output_files()
    assert set(produced) == {
        "requirement-7.2.1.json",
        "requirement-7.2.2.json",
    }
    for filename, content in produced.items():
        golden = (GOLDEN_DIR / "records" / filename).read_text(encoding="utf-8")
        assert content == golden


def test_verbose_logs_page_level_decisions(tmp_path):
    result = run_cli(
        ["--pages", "168", "170", "--extract", "--verbose"], tmp_path / "out"
    )

    assert result.returncode == 0, result.stderr
    debug = [line for line in result.log_lines() if line.startswith("DEBUG")]
    assert any("PDF page 169" in line for line in debug)
    assert any("continued requirement 7.2.1" in line for line in debug)


def test_default_run_hides_debug_logs(tmp_path):
    result = run_cli(["--pages", "168", "170", "--extract"], tmp_path / "out")

    assert not [line for line in result.log_lines() if line.startswith("DEBUG")]
