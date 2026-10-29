"""Unsupported ranges must fail with a clear message and write nothing."""

import pytest

from conftest import GOLDEN_DIR, run_cli

FAILURE_CASES = [
    pytest.param(
        ["--page", "1", "--extract"],
        "Extraction failed: Page 1: no supported sections found",
        id="front-matter-page",
    ),
    pytest.param(
        ["--pages", "43", "50", "--extract"],
        "Extraction failed: Page 43: no supported sections found",
        id="starts-on-introduction-continuation",
    ),
    pytest.param(
        ["--pages", "279", "281", "--extract"],
        "Extraction failed: Page 279: no supported sections found",
        id="starts-on-non-requirement-page",
    ),
    pytest.param(
        ["--pages", "281", "285", "--extract"],
        "Extraction failed: Page 281: 11.4.2 is required. "
        "Extend the page range backwards.",
        id="missing-previous-requirement",
    ),
    pytest.param(
        ["--pages", "330", "340", "--extract"],
        "Extraction failed: Page 330: continuation without "
        "its starting requirement",
        id="continuation-without-start",
    ),
    pytest.param(
        ["--page", "0", "--extract"],
        "Page range must be within 1..397",
        id="page-below-range",
    ),
    pytest.param(
        ["--page", "398", "--extract"],
        "Page range must be within 1..397",
        id="page-above-range",
    ),
    pytest.param(
        ["--pages", "5", "3", "--extract"],
        "Page range must be within 1..397",
        id="reversed-range",
    ),
]


@pytest.mark.parametrize(("args", "message"), FAILURE_CASES)
def test_failure_message_and_no_output(tmp_path, args, message):
    output_dir = tmp_path / "out"

    result = run_cli(args, output_dir)

    assert result.returncode == 1
    assert result.stderr.strip() == message
    assert not output_dir.exists()


def test_partial_range_matches_full_extraction(tmp_path):
    result = run_cli(["--pages", "168", "170", "--extract"], tmp_path / "out")

    assert result.returncode == 0, result.stderr
    assert "Corrected continuation label: PDF page 169, 7.1.2 -> 7.2.1" in (
        result.stdout
    )

    produced = result.output_files()
    assert set(produced) == {
        "requirement-7.2.1.json",
        "requirement-7.2.2.json",
    }
    for filename, content in produced.items():
        golden = (GOLDEN_DIR / "records" / filename).read_text(encoding="utf-8")
        assert content == golden
