"""Rewrites a question into search queries phrased in the standard's own terminology."""

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from config import MAX_REWRITE_QUERIES, REWRITE_WORKERS
from errors import GenerationError
from generate import run_claude_cli

logger = logging.getLogger("pci_extractor")

SYSTEM_PROMPT = f"""You prepare search queries for a PCI DSS v4.0.1 requirements search engine.
Given a user question, output JSON only: {{"queries": ["...", ...]}}.
Rules:
- Rewrite each query in the terminology the PCI DSS standard itself uses, keeping the user's meaning.
- If the question asks for several distinct things, output one query per distinct thing (at most {MAX_REWRITE_QUERIES}). Otherwise output exactly one query.
- Do not answer the question. Do not mention requirement numbers. Each query is one short sentence.
"""


def parse_queries(reply: str) -> list[str]:
    text = reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    queries = json.loads(text)["queries"]
    if not isinstance(queries, list):
        raise ValueError("queries is not a list")
    cleaned = [query.strip() for query in queries if isinstance(query, str) and query.strip()]
    if not cleaned:
        raise ValueError("no usable queries")
    return cleaned[:MAX_REWRITE_QUERIES]


class QueryRewriter:
    """Falls back to the original question whenever a rewrite is unavailable, so search never breaks.

    `cache_only` lets dry runs and offline checks reuse earlier rewrites without calling a model.
    """

    def __init__(self, model: str, cache_path: Path, cache_only: bool = False) -> None:
        self.model = model
        self.cache_path = cache_path
        self.cache_only = cache_only
        self._lock = Lock()
        self._cache = self._load()
        self._fallbacks: dict[str, list[str]] = {}

    def _load(self) -> dict[str, list[str]]:
        if not self.cache_path.is_file():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Ignoring unreadable rewrite cache: %s", self.cache_path)
            return {}

    def _key(self, question: str) -> str:
        digest = hashlib.sha256(f"{self.model}\n{SYSTEM_PROMPT}\n{question}".encode("utf-8"))
        return digest.hexdigest()

    def _store(self, key: str, queries: list[str]) -> None:
        with self._lock:
            self._cache[key] = queries
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._cache, indent=1), encoding="utf-8")
            temporary.replace(self.cache_path)

    def _fall_back(self, key: str, question: str) -> list[str]:
        # Remembered for this process only, so a failed call is not repeated and nothing bad is cached.
        with self._lock:
            self._fallbacks[key] = [question]
        return [question]

    def rewrite(self, question: str) -> list[str]:
        key = self._key(question)
        with self._lock:
            known = self._cache.get(key) or self._fallbacks.get(key)
        if known:
            return known
        if self.cache_only:
            logger.warning("No cached rewrite and no model call allowed; using the original question")
            return self._fall_back(key, question)
        try:
            reply = run_claude_cli(SYSTEM_PROMPT, f"Question: {question}", self.model)
            queries = parse_queries(reply)
        except GenerationError as error:
            logger.warning("Rewrite failed (%s); using the original question", error)
            return self._fall_back(key, question)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            logger.warning("Rewrite reply was not usable (%s); using the original question", error)
            return self._fall_back(key, question)
        self._store(key, queries)
        return queries

    def rewrite_many(self, questions: list[str], workers: int = REWRITE_WORKERS) -> None:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(self.rewrite, questions))
