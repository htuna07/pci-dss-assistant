"""Minimal Okapi BM25 over pre-tokenized documents."""

import math
import re
from collections import Counter

STOP_WORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in is it its "
    "my of on or our should that the their there this to we what when which who "
    "will with you your".split()
)
REQUIREMENT_ID = re.compile(r"\d+(?:\.\d+)+")
WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Keep requirement IDs whole so "8.4.2" is not split into "8", "4", "2"."""
    lowered = text.lower()
    tokens = REQUIREMENT_ID.findall(lowered)
    tokens += [
        word
        for word in WORD.findall(REQUIREMENT_ID.sub(" ", lowered))
        if word not in STOP_WORDS
    ]
    return tokens


class BM25Index:
    def __init__(
        self, documents: list[list[str]], k1: float = 1.5, b: float = 0.75
    ) -> None:
        self.k1 = k1
        self.b = b
        self.term_counts = [Counter(document) for document in documents]
        self.lengths = [len(document) for document in documents]
        self.average_length = sum(self.lengths) / len(documents)
        document_frequency: Counter[str] = Counter()
        for counts in self.term_counts:
            document_frequency.update(counts.keys())
        total = len(documents)
        self.idf = {
            term: math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        scores = []
        for counts, length in zip(self.term_counts, self.lengths):
            norm = self.k1 * (1 - self.b + self.b * length / self.average_length)
            score = 0.0
            for term in set(query_tokens):
                frequency = counts.get(term)
                if frequency:
                    score += self.idf[term] * frequency * (self.k1 + 1) / (frequency + norm)
            scores.append(score)
        return scores
