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
