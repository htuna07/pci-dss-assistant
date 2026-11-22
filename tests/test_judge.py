"""Faithfulness judge: the model call is replaced, so no real call is made."""

import json
import sys

import pytest

from conftest import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "src"))

import judge  # noqa: E402
from errors import GenerationError  # noqa: E402

SOURCES = [
    {"id": "10.5.1", "kind": "requirement", "text": "Retain audit log history for 12 months."},
    {"id": "8.3.6", "kind": "requirement", "text": "Passwords have at least 12 characters."},
]
ANSWER = "Keep logs for 12 months [10.5.1]."
CLEAN_REPLY = json.dumps({"checked": 1, "problems": []})


@pytest.fixture
def fake_model(monkeypatch):
    calls = []

    def fake(system_prompt, user_prompt, model):
        calls.append(user_prompt)
        return fake.reply

    fake.reply = CLEAN_REPLY
    monkeypatch.setattr(judge, "run_claude_cli", fake)
    fake.calls = calls
    return fake


def test_only_the_cited_sources_reach_the_judge(fake_model, tmp_path):
    cache = judge.JudgmentCache(tmp_path / "judgments.json")

    judge.judge_answer(cache, "m", "How long?", SOURCES, ANSWER)

    assert 'id="10.5.1"' in fake_model.calls[0]
    assert "8.3.6" not in fake_model.calls[0]


def test_a_cited_id_without_a_source_is_named_to_the_judge(fake_model, tmp_path):
    cache = judge.JudgmentCache(tmp_path / "judgments.json")

    judge.judge_answer(cache, "m", "How long?", SOURCES, "Logs [10.5.1] and policy [12.8].")

    assert "Cited IDs with no source here: 12.8" in fake_model.calls[0]


def test_problems_are_returned_and_the_answer_is_judged_once(fake_model, tmp_path):
    fake_model.reply = json.dumps(
        {"checked": 2, "problems": [{"text": "36 months", "cited": ["10.5.1"], "verdict": "unsupported", "evidence": ""}]}
    )
    cache = judge.JudgmentCache(tmp_path / "judgments.json")

    first = judge.judge_answer(cache, "m", "How long?", SOURCES, ANSWER)
    second = judge.judge_answer(cache, "m", "How long?", SOURCES, ANSWER)

    assert judge.flagged(first)[0]["verdict"] == "unsupported"
    assert second == first
    assert len(fake_model.calls) == 1


def test_cached_only_never_calls_the_model(fake_model, tmp_path):
    cache = judge.JudgmentCache(tmp_path / "judgments.json")

    assert judge.judge_answer(cache, "m", "How long?", SOURCES, ANSWER, cached_only=True) is None
    assert fake_model.calls == []


@pytest.mark.parametrize("reply", ["not json", '{"checked": 1}', '{"checked": 1, "problems": [{"text": "x", "verdict": "fine"}]}'])
def test_an_unusable_judgment_fails_instead_of_counting_as_faithful(fake_model, tmp_path, reply):
    fake_model.reply = reply
    cache = judge.JudgmentCache(tmp_path / "judgments.json")

    with pytest.raises(GenerationError):
        judge.judge_answer(cache, "m", "How long?", SOURCES, ANSWER)
    assert cache.entries == {}
