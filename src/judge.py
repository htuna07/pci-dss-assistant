"""Faithfulness judge: does every claim in an answer follow from the sources it cites?

The deterministic check only proves that a cited ID was among the sources; it cannot tell
whether that source says what the sentence claims. A stronger model reads both and rules claim
by claim."""

import hashlib
import json
from pathlib import Path

from errors import GenerationError
from generate import cited_ids, format_sources, run_claude_cli

DEFAULT_JUDGE_MODEL = "claude-opus-5-5"
JUDGE_CACHE_NAME = "judgments.json"
VERDICTS = ("partial", "unsupported", "wrong_citation")

JUDGE_PROMPT = """You check whether an ANSWER stays faithful to the SOURCES it cites. You are not checking whether the standard is right, and you must not use outside knowledge: judge only against the sources in the message. Only the sources the answer cites are included; a claim that cites an ID with no source here counts as unsupported.

Split the answer into its factual claims. Skip sentences that only say something is not covered by the sources, greetings and pure advice to consult someone. Check each claim against its cited source:
- supported: the cited source states it. Do not list supported claims.
- partial: the sources support part of the claim but the claim adds a detail, widens the scope or hardens the wording (for example "may" became "must", "at least" was dropped, a condition was left out).
- unsupported: the sources do not state it, or contradict it (numbers, periods, frequencies, who or what is covered).
- wrong_citation: another source given here states it, but the requirement it cites does not.

Be strict about numbers, periods, frequencies, "must" versus "should", "all" versus "some", and who the rule applies to. A claim that paraphrases the source faithfully is supported even if the words differ.

Reply with JSON only, listing ONLY the claims that are not supported:
{"checked": <how many claims you checked>, "problems": [{"text": "<the claim, in the answer's words>", "cited": ["<ids>"], "verdict": "partial|unsupported|wrong_citation", "evidence": "<a short quote from the source that decides it, or empty if there is none>"}]}"""


def build_judge_input(question: str, sources: list[dict], answer: str) -> str:
    """Only the cited sources: the judge needs what each sentence leans on, and the other
    retrieved requirements triple the input without bearing on faithfulness."""
    cited = cited_ids(answer)
    given = [source for source in sources if source["id"] in cited]
    missing = [rid for rid in cited if rid not in {source["id"] for source in given}]
    note = f"\n\nCited IDs with no source here: {', '.join(missing)}" if missing else ""
    return f"Sources:\n\n{format_sources(given)}{note}\n\nQuestion: {question}\n\nANSWER:\n{answer}"


def parse_judgment(reply: str) -> dict:
    text = reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(text)
    problems = data["problems"]
    if not isinstance(problems, list) or not isinstance(data["checked"], int):
        raise ValueError("unusable judgment")
    for claim in problems:
        if claim.get("verdict") not in VERDICTS or not isinstance(claim.get("text"), str):
            raise ValueError(f"unusable claim: {claim!r}")
    return {"checked": data["checked"], "problems": problems}


class JudgmentCache:
    """Keyed by judge model, judge rules and the full input, so a changed answer, source set or
    rule is judged again and nothing else is paid for twice. The file may quote the standard in
    its evidence, so it belongs under the gitignored data/ folder."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, dict] = {}
        if path.is_file():
            self.entries = json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def key(model: str, judge_input: str) -> str:
        digest = hashlib.sha256()
        for part in (model, JUDGE_PROMPT, judge_input):
            digest.update(part.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def get(self, key: str) -> dict | None:
        return self.entries.get(key)

    def put(self, key: str, judgment: dict) -> None:
        self.entries[key] = judgment
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=1) + "\n", encoding="utf-8")


def judge_answer(
    cache: JudgmentCache, model: str, question: str, sources: list[dict], answer: str,
    cached_only: bool = False,
) -> dict | None:
    """{"checked": n, "problems": [...]}, or None when `cached_only` and nothing is cached.

    Raises GenerationError when the model call or its reply is unusable; a failed judgment must
    never count as "faithful"."""
    judge_input = build_judge_input(question, sources, answer)
    key = JudgmentCache.key(model, judge_input)
    judgment = cache.get(key)
    if judgment is not None or cached_only:
        return judgment
    reply = run_claude_cli(JUDGE_PROMPT, judge_input, model)
    try:
        judgment = parse_judgment(reply)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise GenerationError(f"unreadable judgment: {reply[:200]!r}") from error
    cache.put(key, judgment)
    return judgment


def flagged(judgment: dict) -> list[dict]:
    return judgment["problems"]
