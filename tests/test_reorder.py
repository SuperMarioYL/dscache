"""Tests for the reorder-suggestion logic and the wrapper pass-through."""

from __future__ import annotations

from dscache.profiler import profile
from dscache.reorder import suggest_reorder, worst_bust
from dscache.wrapper import wrap


def _busted_ledger():
    return [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 950,
         "miss_tokens": 50, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:CHANGED\nuser:a"},
    ]


def test_worst_bust_identifies_the_miss():
    entries = profile(_busted_ledger())
    target = worst_bust(entries)
    assert target is not None
    assert target.request_id == "r2"


def test_suggest_reorder_returns_concrete_message():
    entries = profile(_busted_ledger())
    suggestion = suggest_reorder(entries)
    assert suggestion is not None
    assert suggestion.request_id == "r2"
    assert suggestion.busted_against == "r1"
    assert "r1" in suggestion.message
    assert suggestion.wasted > 0


def test_suggest_reorder_none_when_stable():
    stable = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 950,
         "miss_tokens": 50, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 950,
         "miss_tokens": 50, "prefix_sample": "system:stable\nuser:a"},
    ]
    assert suggest_reorder(profile(stable)) is None


# --- wrapper pass-through ---------------------------------------------------


class _FakeUsage:
    prompt_tokens = 1000
    prompt_cache_hit_tokens = 900
    prompt_cache_miss_tokens = 100


class _FakeResponse:
    id = "chatcmpl-xyz"
    model = "deepseek-chat"
    usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return _FakeResponse()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()
        self.api_key = "sk-test"


def test_wrap_is_transparent_and_logs(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    client = _FakeClient()
    wrapped = wrap(client, ledger_path=ledger)

    # Pass-through: arbitrary attributes still reach the underlying client.
    assert wrapped.api_key == "sk-test"

    resp = wrapped.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "system", "content": "stable prefix"}],
    )
    assert resp.id == "chatcmpl-xyz"  # original response returned unchanged
    assert client.chat.completions.calls == 1

    entries = profile(_load(ledger))
    assert len(entries) == 1
    assert entries[0].cached_tokens == 900
    assert entries[0].miss_tokens == 100


def test_wrap_never_breaks_caller_when_usage_missing(tmp_path):
    ledger = tmp_path / "ledger.jsonl"

    class _NoUsageResponse:
        id = "chatcmpl-nousage"
        model = "deepseek-chat"
        usage = None

    class _NoUsageCompletions:
        def create(self, **kwargs):
            return _NoUsageResponse()

    class _NoUsageChat:
        completions = _NoUsageCompletions()

    class _NoUsageClient:
        chat = _NoUsageChat()

    wrapped = wrap(_NoUsageClient(), ledger_path=ledger)
    resp = wrapped.chat.completions.create(messages=[{"role": "user", "content": "hi"}])
    # The call still succeeds even though cache fields are absent.
    assert resp.id == "chatcmpl-nousage"
    entries = profile(_load(ledger))
    assert entries[0].cached_tokens is None


def _load(path):
    import json

    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
