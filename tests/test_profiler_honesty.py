"""Honesty regression tests for the v0.2.0 profiler fixes.

Covers:
- fix-same-fingerprint-miss-not-busted: a real MISS/PARTIAL whose sampled 2048-
  char head collides with a prior HIT is still flagged busted, not "stable".
- fix-unknown-tier-fabricates-wasted-money: UNKNOWN-tier requests (DeepSeek
  omitted the cache split) contribute zero phantom wasted ¥ to the headline.
- fix-busted-against-wrong-reference-request: a bust is attributed to the most-
  recent-HIT, not merely the immediately-previous (possibly unstable) request.
"""

from __future__ import annotations

from decimal import Decimal

from rich.console import Console

from dscache.profiler import Tier, profile
from dscache.report import render_headline


# --- fix-same-fingerprint-miss-not-busted -----------------------------------


def test_collided_fingerprint_miss_is_still_busted():
    # r1 establishes a prefix and HITs. r2 has the SAME sampled head (identical
    # prefix_sample -> identical fingerprint) but DeepSeek reports a real MISS:
    # the 2048-char sample is only a lower bound on the true cache key, so this
    # is a genuine bust that must NOT be reported as "cache held stable".
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:stable\nuser:a"},
    ]
    entries = profile(records)
    assert entries[0].tier is Tier.HIT
    assert entries[1].tier is Tier.MISS
    # Fingerprints collide...
    assert entries[0].prefix_fingerprint == entries[1].prefix_fingerprint
    # ...yet the MISS is still flagged busted against the fingerprint's owner.
    assert entries[1].busted_against == "r1"


def test_collided_fingerprint_partial_is_busted():
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 500,
         "miss_tokens": 500, "prefix_sample": "system:stable\nuser:a"},
    ]
    entries = profile(records)
    assert entries[1].tier is Tier.PARTIAL
    assert entries[1].busted_against == "r1"


def test_collided_fingerprint_hit_is_not_busted():
    # A genuine HIT whose fingerprint matches a prior HIT is NOT a bust.
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:stable\nuser:a"},
    ]
    entries = profile(records)
    assert entries[1].tier is Tier.HIT
    assert entries[1].busted_against is None


# --- fix-unknown-tier-fabricates-wasted-money -------------------------------


def test_unknown_tier_contributes_zero_waste():
    # DeepSeek omitted the cache split -> UNKNOWN. No phantom waste.
    records = [
        {"request_id": "r1", "prompt_tokens": 4000},  # no cached/miss fields
    ]
    entries = profile(records)
    assert entries[0].tier is Tier.UNKNOWN
    assert entries[0].cost_ideal == entries[0].cost_actual
    assert entries[0].wasted == Decimal("0")


def test_headline_excludes_unknown_from_wasted_and_ratio():
    # A run of nothing-but-UNKNOWN must NOT print a large wasted/4.00x ratio.
    records = [
        {"request_id": f"r{i}", "prompt_tokens": 4000} for i in range(5)
    ]
    entries = profile(records)
    panel = render_headline(entries)
    rendered = _render(panel)
    assert "wasted" not in rendered.lower() or "¥0" in rendered
    assert "Cache held stable" in rendered


def test_headline_unknown_does_not_dilute_real_bust():
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 950,
         "miss_tokens": 50, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 4000},  # UNKNOWN, no fields
        {"request_id": "r3", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:CHANGED\nuser:a"},
    ]
    entries = profile(records)
    # Only the real MISS busts; the UNKNOWN never fabricates a bust or waste.
    assert entries[1].busted_against is None
    assert entries[1].wasted == Decimal("0")
    panel = render_headline(entries)
    assert "busted the cache 1" in _render(panel)


# --- fix-busted-against-wrong-reference-request -----------------------------


def test_busted_against_is_most_recent_hit_not_immediate_neighbor():
    # r1 HIT (stable), r2 MISS (unstable, busts), r3 MISS again. The naive
    # implementation would point r3 at r2 (its immediate neighbor, itself
    # unstable). The fix points r3 at the most-recent HIT (r1).
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:stableA\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:junkB\nuser:a"},
        {"request_id": "r3", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:junkC\nuser:a"},
    ]
    entries = profile(records)
    assert entries[1].busted_against == "r1"  # first bust references the HIT
    assert entries[2].busted_against == "r1"  # second bust ALSO references the HIT


def test_busted_against_falls_back_to_neighbor_when_no_prior_hit():
    # No request ever HIT, so there is no stable reference; fall back to the
    # immediate neighbor rather than crashing or leaving it None.
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 500,
         "miss_tokens": 500, "prefix_sample": "system:a\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:b\nuser:a"},
    ]
    entries = profile(records)
    assert entries[0].tier is Tier.PARTIAL
    assert entries[1].busted_against == "r1"  # neighbor fallback


# --- fix-bust-reference-quality-miss-owner-and-unknown-fallback -------------


def test_miss_does_not_register_as_fingerprint_owner_when_prior_hit_exists():
    # r0 HIT (stable prefix STABLE). r1 MISS with a NEW prefix A. r2 MISS with
    # the SAME prefix A. The old code registered r1 (a MISS) as the owner of A,
    # so r2's collision busted against r1 — an UNSTABLE reference. The fix
    # skips registering a MISS, so r2 falls through to the bust_reference path
    # and is attributed to the prior HIT (r0), the stable reference.
    records = [
        {"request_id": "r0", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:STABLE\nuser:a"},
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:AAA\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:AAA\nuser:a"},  # same as r1
    ]
    entries = profile(records)
    assert entries[0].tier is Tier.HIT
    assert entries[1].tier is Tier.MISS
    assert entries[2].tier is Tier.MISS
    # r1 (MISS) is NOT the owner; r2 busts against the prior HIT r0, not r1.
    assert entries[1].busted_against == "r0"
    assert entries[2].busted_against == "r0"  # NOT "r1"


def test_unknown_does_not_become_last_request_fallback():
    # r1 UNKNOWN (no cache fields). r2 MISS with a new prefix. The old code
    # advanced last_request_id on the UNKNOWN entry, so r2's no-prior-HIT
    # fallback pointed at r1 — a request whose cache split was never reported.
    # The fix only advances last_request_id on JUDGED entries, so r2 has no
    # judged neighbor to fall back to and is left un-attributed rather than
    # pointing at an UNKNOWN.
    records = [
        {"request_id": "r1", "prompt_tokens": 4000},  # UNKNOWN, no fields
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:new\nuser:a"},
    ]
    entries = profile(records)
    assert entries[0].tier is Tier.UNKNOWN
    assert entries[1].tier is Tier.MISS
    # r2 cannot be attributed to the UNKNOWN r1 — it stays None.
    assert entries[1].busted_against is None


# --- fix-cost-actual-drops-split-gap-tokens ---------------------------------


def test_miss_with_inconsistent_split_never_negative_waste():
    # The v0.3.0 cost_ideal fix raised the ideal to prompt_tokens*hit but left
    # cost_actual pricing ONLY cached+miss, so when the provider's split was
    # inconsistent (cached+miss < prompt_tokens) the unaccounted gap was free
    # and a cache MISS could render NEGATIVE waste — "cheaper than ideal" —
    # which then subtracted from the headline's total wasted ¥. Reproduced
    # wasted = -0.000045 on a tier=MISS (cached=10, miss=100, prompt=500). The
    # fix prices the gap (prompt−cached−miss) at the miss rate inside
    # cost_actual so cost_actual ≥ cost_ideal always (fix
    # fix-cost-actual-drops-split-gap-tokens); the consistent-split case is
    # unchanged.
    from dscache.profiler import price_request

    cached, miss, prompt = 10, 100, 500  # cached + miss = 110 < 500
    actual, ideal = price_request(cached, miss, prompt)
    # cost_actual is never below the prompt-based cost_ideal — a MISS can no
    # longer show negative waste.
    assert actual >= ideal
    assert actual - ideal >= Decimal("0")
    # Exact figures: gap=390 priced at the miss rate on top of cached+miss.
    assert actual == Decimal("0.000985")  # 10*0.5/1M + 100*2/1M + 390*2/1M
    assert ideal == Decimal("0.000250")  # 500 * 0.5 / 1M
    # The v0.3.0 code priced only cached+miss (0.000205) and so rendered
    # wasted = 0.000205 - 0.000250 = -0.000045 — the exact negative the fix
    # removes.
    assert Decimal("0.000205") - ideal < Decimal("0")


def test_headline_miss_with_inconsistent_split_never_negative():
    # The negative per-request waste used to subtract from the headline's total,
    # understating the central "busted N×, cost X.Yx, ¥Z wasted" number. A run
    # whose only judged request is such a MISS must show a NON-negative headline
    # total — no negative waste to subtract.
    from dscache.report import _headline_numbers

    records = [
        {"request_id": "r1", "prompt_tokens": 500, "cached_tokens": 10,
         "miss_tokens": 100, "prefix_sample": "system:a\nuser:b"},
    ]
    entries = profile(records)
    e = entries[0]
    assert e.tier is Tier.MISS
    assert e.wasted >= Decimal("0")  # per-request waste never negative
    assert e.cost_actual >= e.cost_ideal
    # Headline total wasted is non-negative (no negative per-request waste to
    # subtract from the headline).
    nums = _headline_numbers(entries)
    assert nums["wasted"] >= Decimal("0")


def _render(panel) -> str:
    console = Console(width=120, record=True)
    console.print(panel)
    return console.export_text()
