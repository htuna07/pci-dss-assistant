"""Build the answer prompt from retrieved requirements and run the generator."""

import json
import re
import subprocess
import tempfile

from config import GENERATION_TIMEOUT_SECONDS, NOT_FOUND_REPLY
from errors import GenerationError

SYSTEM_PROMPT = f"""You answer questions about the PCI DSS v4.0.1 standard using ONLY the sources provided in the user message.

Rules:
- Follow every statement of fact with the requirement ID it comes from, in square brackets, for example [8.4.2].
- Use only requirement IDs that appear in the sources. Never invent or recall other requirement IDs.
- Do not use knowledge from outside the sources, even if you know the answer.
- Sources marked as introductions give background only; do not present them as requirements.
- If the sources do not contain the answer, reply exactly: {NOT_FOUND_REPLY}
- If the sources answer only part of the question, answer that part and say which part is not covered.
- Be concise and use plain language."""

CITATION_GROUP = re.compile(r"\[([\d.,;\s]+)\]")
CITED_ID = re.compile(r"\d+(?:\.\d+)*")


def group_sources(chunks: list[dict], requirement_ids: list[str]) -> list[dict]:
    by_requirement: dict[str, list[dict]] = {}
    for chunk in chunks:
        by_requirement.setdefault(chunk["requirement_id"], []).append(chunk)

    sources = []
    for requirement_id in requirement_ids:
        members = by_requirement[requirement_id]
        kind = (
            "introduction"
            if members[0]["record_type"] == "requirement_introduction"
            else "requirement"
        )
        text = "\n\n".join(
            f"{chunk['header'].splitlines()[0]}\n{chunk['text']}" for chunk in members
        )
        sources.append({"id": requirement_id, "kind": kind, "text": text})
    return sources


def format_sources(sources: list[dict]) -> str:
    return "\n\n".join(
        f'<source id="{source["id"]}" kind="{source["kind"]}">\n{source["text"]}\n</source>'
        for source in sources
    )


def build_sources(chunks: list[dict], requirement_ids: list[str]) -> str:
    return format_sources(group_sources(chunks, requirement_ids))


def build_user_prompt(question: str, sources: str) -> str:
    return f"Sources:\n\n{sources}\n\nQuestion: {question}"


def failure_detail(completed: subprocess.CompletedProcess) -> str:
    """`claude --output-format json` reports errors such as "Not logged in" on stdout, not stderr."""
    try:
        message = json.loads(completed.stdout).get("result")
    except (json.JSONDecodeError, AttributeError):
        message = None
    return (message if isinstance(message, str) and message else completed.stderr).strip()[:300]


def run_claude_cli(system_prompt: str, user_prompt: str, model: str) -> str:
    """Runs from an empty directory with no tools so the model sees only the prompt."""
    command = [
        "claude", "-p",
        "--model", model,
        "--system-prompt", system_prompt,
        "--tools", "",
        "--restricted",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--output-format", "json",
    ]
    with tempfile.TemporaryDirectory() as empty_dir:
        try:
            completed = subprocess.run(
                command,
                input=user_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=empty_dir,
                timeout=GENERATION_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as error:
            raise GenerationError("the `claude` command was not found") from error
        except subprocess.TimeoutExpired as error:
            raise GenerationError(
                f"the generator took longer than {GENERATION_TIMEOUT_SECONDS}s"
            ) from error

    if completed.returncode != 0:
        raise GenerationError(f"claude exited with {completed.returncode}: {failure_detail(completed)}")
    try:
        reply = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise GenerationError(f"unreadable claude output: {completed.stdout[:300]!r}") from error
    if reply.get("is_error") or not isinstance(reply.get("result"), str):
        raise GenerationError(f"claude reported an error: {str(reply)[:300]}")
    return reply["result"].strip()


def cited_ids(answer: str) -> list[str]:
    found: list[str] = []
    for group in CITATION_GROUP.findall(answer):
        found += CITED_ID.findall(group)
    return list(dict.fromkeys(found))


def check_answer(answer: str, retrieved_ids: list[str]) -> dict:
    cited = cited_ids(answer)
    return {
        "cited": cited,
        "outside_sources": [rid for rid in cited if rid not in retrieved_ids],
        "not_found": answer.strip().startswith(NOT_FOUND_REPLY),
    }
