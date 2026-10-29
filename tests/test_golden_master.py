"""Compare the full extraction against reviewed reference output.

The golden files were produced by the extraction code before the
refactor and match the previously reviewed `data/processed/` output.
Update them only after confirming that an output change is intentional.
"""

import pytest

from conftest import GOLDEN_DIR, run_cli

GOLDEN_RECORDS = {
    path.name: path.read_text(encoding="utf-8")
    for path in sorted((GOLDEN_DIR / "records").glob("*.json"))
}


def test_full_extraction_succeeds(full_extraction):
    assert full_extraction.returncode == 0, full_extraction.stderr


def test_same_set_of_files(full_extraction):
    produced = set(full_extraction.output_files())
    expected = set(GOLDEN_RECORDS)

    assert sorted(produced - expected) == []
    assert sorted(expected - produced) == []


@pytest.mark.parametrize("filename", sorted(GOLDEN_RECORDS))
def test_record_matches_golden(full_extraction, filename):
    produced = full_extraction.output_files().get(filename)

    assert produced is not None, f"{filename} was not written"
    assert produced == GOLDEN_RECORDS[filename]


def test_saved_files_report_matches_golden(full_extraction):
    expected = (GOLDEN_DIR / "extract_pages_42_337.stdout").read_text(
        encoding="utf-8"
    )

    assert full_extraction.normalized_stdout() == expected


def test_decision_log_matches_golden(full_extraction):
    expected = (GOLDEN_DIR / "extract_pages_42_337.stderr").read_text(
        encoding="utf-8"
    )

    assert full_extraction.stderr == expected


@pytest.mark.parametrize(
    ("args", "golden_name"),
    [
        (["--page", "44", "--inspect"], "inspect_page_44.stdout"),
        (["--pages", "281", "282", "--inspect"], "inspect_pages_281_282.stdout"),
    ],
)
def test_inspect_output_matches_golden(tmp_path, args, golden_name):
    result = run_cli(args, tmp_path / "out")

    assert result.returncode == 0, result.stderr
    assert result.stdout == (GOLDEN_DIR / golden_name).read_text(
        encoding="utf-8"
    )
    assert result.output_files() == {}
