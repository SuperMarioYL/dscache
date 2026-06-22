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
        f"diverged from request {target.busted_against}. Pin the system prompt "
        f"and tool list to the exact byte order used in {target.busted_against} "
        f"(move any per-call dynamic content, e.g. timestamps, below the stable "
        f"prefix) to recover the cache discount.\n"
        f"{attribution.message}"
    )

    return ReorderSuggestion(
        request_id=target.request_id,
        busted_against=target.busted_against,
        wasted=target.wasted,
        message=message,
        attribution=attribution,
    )


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
