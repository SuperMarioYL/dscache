"""Tests for the core profiling primitive."""

from __future__ import annotations

from decimal import Decimal

from dscache.profiler import (
    Tier,
    derive_tier,
    entry_from_record,
    fingerprint_prefix,
    price_request,
    profile,
)


def test_derive_tier_hit_partial_miss():
    assert derive_tier(1000, 950) is Tier.HIT
    assert derive_tier(1000, 500) is Tier.PARTIAL
    assert derive_tier(1000, 50) is Tier.MISS


def test_derive_tier_unknown_when_cache_field_missing():
    # DeepSeek cache fields are unverified — a missing field must NOT crash.
    assert derive_tier(1000, None) is Tier.UNKNOWN
    assert derive_tier(0, 0) is Tier.UNKNOWN


def test_fingerprint_is_stable_and_distinguishing():
    a = fingerprint_prefix("system:stable prefix\nuser:hello")
    b = fingerprint_prefix("system:stable prefix\nuser:hello")
    c = fingerprint_prefix("system:DIFFERENT prefix\nuser:hello")
    assert a == b
    assert a != c
    assert fingerprint_prefix(None) is None
    assert fingerprint_prefix("") is None


def test_price_request_two_tier():
    # 1000 cached + 1000 miss tokens.
    actual, ideal = price_request(1000, 1000, 2000)
    # cached at 0.5/1M, miss at 2.0/1M
    assert actual == Decimal("0.002500")
    # ideal: all 2000 cached at 0.5/1M
    assert ideal == Decimal("0.001000")
    assert actual > ideal


def test_price_request_degrades_when_split_unknown():
    # Provider omitted the cache split — must not raise; prices defensively.
    actual, ideal = price_request(None, None, 1000)
    assert actual == Decimal("0.002000")  # whole prompt at miss rate
    assert ideal == Decimal("0.000500")  # whole prompt at hit rate


def test_price_request_ideal_uses_prompt_tokens_when_split_inconsistent():
    # fix-cost-ideal-uses-prompt-tokens-not-split-sum: the ideal is the
    # "entire prompt cached" counterfactual, so it must be prompt_tokens * hit
    # rate, NOT (cached + miss) * hit rate. Providers surface inconsistent
    # splits (cached + miss != prompt_tokens); the old code understated the
    # ideal and fabricated phantom wasted ¥.
    cached, miss, prompt = 800, 100, 1000  # cached + miss = 900 != 1000
    actual, ideal = price_request(cached, miss, prompt)
    # actual: 800 cached at hit + 100 miss at miss rate + the 100-token
    # unaccounted split gap (prompt−cached−miss) priced at the miss rate, so
    # cost_actual ≥ cost_ideal always (fix
    # fix-cost-actual-drops-split-gap-tokens).
    assert actual == Decimal("0.000800")  # 800*0.5/1M + 100*2.0/1M + 100*2.0/1M (gap)
    # ideal: the FULL 1000-prompt cached, NOT the 900 split sum.
    assert ideal == Decimal("0.000500")  # 1000 * 0.5 / 1M
    # A MISS can no longer render negative waste against the prompt-based ideal.
    assert actual >= ideal
    # And the consistent case is unchanged (split sum == prompt -> gap=0).
    assert price_request(1000, 1000, 2000)[0] == Decimal("0.002500")
    assert price_request(1000, 1000, 2000)[1] == Decimal("0.001000")


def test_entry_from_record_infers_missing_side():
    e = entry_from_record(
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 800}
    )
    assert e.miss_tokens == 200  # inferred from prompt - cached


def test_entry_from_record_handles_garbage():
    # Malformed provider data should coerce to None / 0, never raise.
    e = entry_from_record(
        {"request_id": "r1", "prompt_tokens": "oops", "cached_tokens": None}
    )
    assert e.prompt_tokens == 0
    assert e.cached_tokens is None
    assert e.tier is Tier.UNKNOWN or e.tier == Tier.UNKNOWN


def test_profile_tags_busted_request():
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 950,
         "miss_tokens": 50, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 950,
         "miss_tokens": 50, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r3", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:CHANGED\nuser:a"},
    ]
    entries = profile(records)
    assert [e.tier for e in entries] == [Tier.HIT, Tier.HIT, Tier.MISS]
    assert entries[2].busted_against == "r2"
    assert entries[2].wasted > 0


def test_profile_empty():
    assert profile([]) == []
