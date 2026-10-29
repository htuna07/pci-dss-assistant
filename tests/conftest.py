"""Behavioral tests drive the extraction CLI as a subprocess.

Only the command line and the files it writes are asserted, so the
implementation behind `src/main.py` can be refactored freely.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_SCRIPT = PROJECT_ROOT / "src" / "main.py"
PDF_PATH = PROJECT_ROOT / "data" / "PCI-DSS-v4_0_1.pdf"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

FULL_RANGE = (42, 337)


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    output_dir: Path

    def normalized_stdout(self) -> str:
        return self.stdout.replace(str(self.output_dir), "<output-dir>")

    def log_lines(self) -> list[str]:
        return [
            line
            for line in self.stderr.splitlines()
            if line.split(" ", 1)[0] in {"DEBUG", "INFO", "WARNING"}
        ]

    def output_files(self) -> dict[str, str]:
        if not self.output_dir.is_dir():
            return {}
        return {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(self.output_dir.glob("*.json"))
        }


def run_cli(args: list[str], output_dir: Path) -> CliResult:
    completed = subprocess.run(
        [sys.executable, str(MAIN_SCRIPT), *args, "--output-dir", str(output_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
    )
    return CliResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        output_dir=output_dir,
    )


@pytest.fixture(scope="session", autouse=True)
def require_pdf() -> None:
    if not PDF_PATH.is_file():
        pytest.skip(f"Source PDF not found: {PDF_PATH}", allow_module_level=True)


@pytest.fixture(scope="session")
def full_extraction(tmp_path_factory: pytest.TempPathFactory) -> CliResult:
    start, end = FULL_RANGE
    return run_cli(
        ["--pages", str(start), str(end), "--extract"],
        tmp_path_factory.mktemp("full_extraction"),
    )
