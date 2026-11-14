"""Download the embedding model and embed every chunk, so later runs start without either step."""

import argparse
from pathlib import Path

from config import DEFAULT_CHUNKS_DIR, DEFAULT_INDEX_DIR, EMBEDDING_MODEL
from embeddings import embed_chunks, load_model
from jsonl_io import read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chunks", type=Path, default=DEFAULT_CHUNKS_DIR / "chunks-grouped.jsonl"
    )
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    args = parser.parse_args()

    chunks = read_jsonl(args.chunks)
    vectors = embed_chunks(chunks, load_model(args.embedding_model), args.embedding_model, args.index_dir)
    print(f"Embedded {len(vectors)} chunks into {args.index_dir}")


if __name__ == "__main__":
    main()
