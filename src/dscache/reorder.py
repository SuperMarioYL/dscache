"""Prefix-reorder suggestions (m2 milestone — stub for v0.1).

Given a profiled ledger with bust events (``busted_against`` links set by
:func:`dscache.profiler.profile`), :func:`suggest_reorder` returns a concrete,
human-readable suggestion for the *worst* bust — the reorder that would have
kept the cached prefix span byte-stable. It never auto-applies: dscache suggests,
it never mutates the request in-flight (an explicit non-goal in the plan).

m1 ships this as a minimal, honest stub: it identifies the worst bust and points
at it. The full stable-span maximizer lands in m2 (``m2_reorder_suggest``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence

from .attribute import SegmentAttribution, attribute_bust
from .profiler import CacheLedgerEntry, Tier
from .report import _headline_numbers


@dataclass
class ReorderSuggestion:
    """A suggested fix for one prefix-bust event."""

    request_id: str
    busted_against: Optional[str]
    wasted: Decimal
    message: str
    #: Segment-level attribution naming the first diverging prompt segment
    #: against the most-recent-HIT reference (feat-segment-level-bust-attribution).
    #: ``None`` only when the busted request's prefix sample was unavailable.
    attribution: Optional[SegmentAttribution] = None


def worst_bust(entries: Sequence[CacheLedgerEntry]) -> Optional[CacheLedgerEntry]:
    """Return the busted entry that wasted the most money, if any."""
    busted = [e for e in entries if e.busted_against is not None]
    if not busted:
        return None
    return max(busted, key=lambda e: e.wasted)


def _pin_clause(attribution: SegmentAttribution, busted_against: Optional[str]) -> str:
    """Build the actionable 'Pin X' clause for a bust suggestion.

    Names the ACTUAL diverging segment the attribution already computed (e.g.
    ``user (segment[2])`` / ``tools[1]``) so the user fixes the segment that
    diverged, not a generic ``system prompt and tool list`` that misleads when
    the bust is in a user message or a specific tool. Falls back to the generic
    line only when no client-side divergence was located (``segment is None`` —
    a clean diff / server-side eviction), the honest answer when no specific
    segment diverged (fix fix-suggest-reorder-names-diverging-segment).
    """
    ref = busted_against or "the prior cached request"
    tail = (
        " (move any per-call dynamic content, e.g. timestamps, below the "
        "stable prefix) to recover the cache discount."
    )
    if attribution.segment is not None:
        return f"Pin {attribution.segment} to the exact byte order used in {ref}{tail}"
    return f"Pin the system prompt and tool list to the exact byte order used in {ref}{tail}"


def suggest_reorder(entries: Sequence[CacheLedgerEntry]) -> Optional[ReorderSuggestion]:
    """Produce a reorder suggestion for the worst bust in the ledger.

    Returns ``None`` when no bust was detected (every request held the cached
    prefix, or there isn't enough signal yet).
    """
    target = worst_bust(entries)
    if target is None:
        return None

    tier_note = {
        Tier.MISS: "completely missed the cache",
        Tier.PARTIAL: "only partially hit the cache",
    }.get(target.tier, "diverged from the cached prefix")

    # Segment-level attribution: diff the busted request head against its
    # most-recent-HIT reference and name the FIRST diverging segment
    # (feat-segment-level-bust-attribution). Detect-only — never mutates.
    reference = _entry_by_id(entries, target.busted_against)
    attribution = attribute_bust(
        target._prefix_sample,
        reference._prefix_sample if reference is not None else None,
        target.busted_against,
    )

    message = (
        f"Request {target.request_id} {tier_note} — its leading prompt span "
        f"diverged from request {target.busted_against}. "
        f"{_pin_clause(attribution, target.busted_against)}\n"
        f"{attribution.message}"
    )

    return ReorderSuggestion(
        request_id=target.request_id,
        busted_against=target.busted_against,
        wasted=target.wasted,
        message=message,
        attribution=attribution,
    )


def no_bust_note(entries: Sequence[CacheLedgerEntry]) -> tuple[str, bool]:
    """Context-aware message for when no prefix-bust was detected.

    :func:`suggest_reorder` returns ``None`` whenever no entry has
    ``busted_against`` set, but "no bust" and "your prefix is stable" are
    different claims. The second is fabricated when dscache has no evidence of
    stability — an all-UNKNOWN run (DeepSeek never reported the cache split, so
    dscache cannot judge hit/miss for any request) or a cold-start run that
    wasted money with no prior stable prefix to bust against (the v0.6.0/v0.7.0
    cold-start fixes correctly suppressed the phantom bust, so suggest_reorder
    is ``None`` even though money was wasted — and the money headline honestly
    says so). Branch on the judged-requests state via the same
    :func:`_headline_numbers` the money headline uses, so ``dscache suggest``
    never contradicts ``dscache report`` for the same ledger (fix
    fix-suggest-fabricates-stable-on-no-bust).

    Returns
    -------
    (message, is_genuinely_stable)
        ``is_genuinely_stable`` is ``True`` only when the run has judged
        requests with zero waste and zero busts — the one case where "your
        prefix is stable" is honest.
    """
    nums = _headline_numbers(entries)
    if nums["total_ideal"] == 0:
        return (
            "No client-side prefix-bust detected — but dscache could not judge "
            "any request (DeepSeek did not report cache-hit/miss fields). Wrap "
            "your client with dscache.wrap(client) and re-run after DeepSeek "
            "surfaces the cache split to see HIT/PARTIAL/MISS.",
            False,
        )
    if nums["wasted"] > 0:
        return (
            f"No client-side prefix-bust detected against a prior stable prefix "
            f"(cold start) — but this run wasted ¥{nums['wasted']:.4f}. Re-run "
            f"after a cache hit so dscache can attribute busts.",
            False,
        )
    return ("No cache-bust detected — your prefix is stable.", True)


def _entry_by_id(
    entries: Sequence[CacheLedgerEntry], request_id: Optional[str]
) -> Optional[CacheLedgerEntry]:
    """Look up a profiled entry by its request_id, if present."""
    if request_id is None:
        return None
    for e in entries:
        if e.request_id == request_id:
            return e
    return None
