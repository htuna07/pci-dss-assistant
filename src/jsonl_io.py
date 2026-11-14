"""Reading JSONL files with a pointer to the step that creates them."""

import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        message = f"File not found: {path}"
        if path.parent.name == "chunks":
            message += "\nBuild the chunks first with: python src/build_chunks.py"
        raise SystemExit(message)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
