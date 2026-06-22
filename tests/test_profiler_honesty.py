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


def _render(panel) -> str:
    console = Console(width=120, record=True)
    console.print(panel)
    return console.export_text()
