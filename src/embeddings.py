"""Sentence embeddings for chunks and queries, with an on-disk cache."""

import hashlib
from pathlib import Path

import numpy as np


def passage_text(chunk: dict) -> str:
    return f"{chunk['header']}\n{chunk['text']}"


def load_model(model_name: str):
    # Imported lazily so keyword-only runs do not pay for loading torch.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def cache_path(chunks: list[dict], model_name: str, index_dir: Path) -> Path:
    digest = hashlib.sha256(model_name.encode("utf-8"))
    for chunk in chunks:
        digest.update(chunk["chunk_id"].encode("utf-8"))
        digest.update(passage_text(chunk).encode("utf-8"))
    return index_dir / f"embeddings-{digest.hexdigest()[:16]}.npy"


def embed_chunks(
    chunks: list[dict], model, model_name: str, index_dir: Path
) -> np.ndarray:
    """Keyed by a hash of model and chunk text, so edited chunks never reuse stale vectors."""
    path = cache_path(chunks, model_name, index_dir)
    if path.is_file():
        return np.load(path)
    vectors = model.encode(
        [passage_text(chunk) for chunk in chunks],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    index_dir.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)
    return vectors


def embed_query(model, query: str, prefix: str) -> np.ndarray:
    return model.encode([prefix + query], normalize_embeddings=True)[0]
