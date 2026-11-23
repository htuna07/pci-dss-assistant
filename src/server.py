"""Local web interface: one page and one JSON endpoint on top of the same pipeline as ask.py."""

import argparse
import os
import sys
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_ANSWER_TOP_K,
    DEFAULT_CHUNKS_DIR,
    DEFAULT_INDEX_DIR,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    EMBEDDING_MODEL,
    MAX_QUESTION_CHARS,
)
from errors import GenerationError
from pipeline import Assistant

PAGE_PATH = Path(__file__).resolve().parent / "web" / "index.html"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


def create_app(assistant: Assistant) -> FastAPI:
    app = FastAPI(title="PCI DSS Assistant", docs_url=None, redoc_url=None)
    # One question at a time: the embedding model and the `claude` calls are shared, and this is
    # a personal local tool, so queueing is simpler and safer than concurrency.
    one_at_a_time = threading.Lock()

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(PAGE_PATH, media_type="text/html")

    @app.post("/api/ask")
    def ask(request: AskRequest) -> dict:
        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="The question is empty.")
        with one_at_a_time:
            try:
                answer = assistant.answer(question)
            except GenerationError as error:
                raise HTTPException(status_code=502, detail=f"Generation failed: {error}") from error
        return {
            "question": question,
            "answer": answer.text,
            "queries": answer.prepared.queries,
            "retrieved": answer.prepared.retrieved,
            "sources": answer.prepared.sources,
            "check": answer.check,
        }

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the PCI DSS assistant in a browser.")
    # Anyone who can reach the port spends the owner's model quota, so the default is this machine only.
    parser.add_argument("--host", default=DEFAULT_SERVER_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    parser.add_argument(
        "--chunks", type=Path, default=DEFAULT_CHUNKS_DIR / "chunks-grouped.jsonl"
    )
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    parser.add_argument("--model", default=DEFAULT_ANSWER_MODEL)
    parser.add_argument("--k", type=int, default=DEFAULT_ANSWER_TOP_K)
    return parser


def warn_if_no_credentials() -> None:
    """A container without a token only fails at the first question, with a generic error."""
    has_env = any(os.environ.get(name) for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"))
    if not has_env and not (Path.home() / ".claude" / ".credentials.json").is_file():
        print(
            "Warning: no CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY is set and no `claude` login "
            "was found; questions will fail until one is provided.",
            file=sys.stderr, flush=True,
        )


def main() -> None:
    args = build_parser().parse_args()
    if args.k < 1:
        raise SystemExit("--k must be at least 1")
    warn_if_no_credentials()
    print("Loading the search index...", flush=True)
    assistant = Assistant.from_files(
        args.chunks,
        args.index_dir,
        args.embedding_model,
        model=args.model,
        k=args.k,
        persist_rewrites=False,
    )
    print(f"Listening on http://{args.host}:{args.port}", flush=True)
    uvicorn.run(create_app(assistant), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
