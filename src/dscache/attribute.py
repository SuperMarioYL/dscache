"""Segment-level bust attribution.

When the profiler detects a prefix bust against its most-recent-HIT reference,
this module diffs the two *serialized request heads* at segment granularity —
which message index, which tool block, or the system text — and names the
**first** diverging segment, e.g.::

    PREFIX BUST: tools[3] reordered vs req r17; messages[0..2] still stable.

This is **detect-and-attribute only**: it never mutates the request. It also
ships with an explicit honesty caveat — a client can reason only about its OWN
prefix divergence. It cannot observe or control DeepSeek's server-side global
LRU eviction, so a clean diff here means "you did not cause this bust on the
client side", NOT "your call was guaranteed a cache hit". Server-side eviction
is invisible from the client and is never attributed here.

The diffable unit is the serialized prefix sample produced by
:func:`dscache.wrapper._prefix_sample`, which (as of v0.2.0) prefixes a
serialization of ``tools`` / ``tool_choice`` / ``response_format`` ahead of the
leading message text. Segments are recovered by splitting that sample back on
the same ``\\n`` boundaries the wrapper writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Honesty caveat surfaced alongside every attribution. dscache reasons only
#: about the client's own prefix divergence — it cannot see DeepSeek's
#: server-side global LRU eviction.
HONESTY_CAVEAT = (
    "Note: this attributes a CLIENT-side prefix divergence only. dscache cannot "
    "observe or control DeepSeek's server-side global LRU cache eviction, so a "
    "stable client prefix is necessary but not sufficient for a cache hit."
)


@dataclass
class SegmentAttribution:
    """The first diverging segment between a bust and its reference request."""

    #: Human-readable label of the first diverging segment, e.g. ``tools[3]``,
    #: ``messages[0]`` or ``system``. ``None`` when no client-side divergence
    #: was found (the bust is then attributable to server-side eviction only).
    segment: Optional[str]
    #: request_id of the most-recent-HIT reference we diffed against.
    reference_request_id: Optional[str]
    #: Inclusive range of leading segments that stayed byte-stable, as a label
    #: like ``messages[0..2]`` or ``segments[0..1]``; ``None`` if nothing matched.
    stable_through: Optional[str]
    #: One-line, copy-pasteable attribution message.
    message: str

    @property
    def diverged(self) -> bool:
        return self.segment is not None


def _segment_label(seg: str, index: int) -> str:
    """Best-effort human label for a serialized prefix segment.

    The wrapper serializes tool blocks as ``tools[i]:...`` and messages as
    ``role:content``; we recover a friendly label from that shape so the
    attribution can say *which* tool or *which* message diverged.
    """
    head = seg.split(":", 1)[0] if ":" in seg else seg
    head = head.strip()
    # Tool blocks carry an explicit ``tools[i]`` / ``tool_choice`` / ``response_format``
    # marker written by the wrapper — surface it verbatim.
    if head.startswith(("tools[", "tool_choice", "response_format")):
        return head
    if head in ("system", "user", "assistant", "tool", "developer"):
        return f"{head} (segment[{index}])"
    return f"segment[{index}]"


def _split_segments(sample: Optional[str]) -> list[str]:
    """Recover the serialized segments the wrapper joined with ``\\n``."""
    if not sample:
        return []
    return sample.split("\n")


def _stable_label(segments: list[str], upto: int) -> Optional[str]:
    """Build a ``...[0..n]`` label for the segments that stayed stable."""
    if upto <= 0:
        return None
    # Prefer a friendly family label when all stable segments share a family.
    last = upto - 1
    return f"segments[0..{last}]"


def attribute_bust(
    busted_sample: Optional[str],
    reference_sample: Optional[str],
    reference_request_id: Optional[str],
) -> SegmentAttribution:
    """Diff two serialized request heads and name the first diverging segment.

    Parameters
    ----------
    busted_sample:
        The serialized prefix sample of the request that busted the cache.
    reference_sample:
        The serialized prefix sample of the most-recent-HIT reference request
        whose prefix the busted call should have reused.
    reference_request_id:
        request_id of that reference, for the message text.

    Returns
    -------
    SegmentAttribution
        ``segment`` is the label of the first diverging segment, or ``None``
        when the two heads are byte-identical over their shared length (a clean
        client-side diff — the bust is then attributable to server-side eviction,
        which dscache cannot observe).
    """
    busted_segs = _split_segments(busted_sample)
    ref_segs = _split_segments(reference_sample)

    ref_tag = reference_request_id or "the prior cached request"
    shared = min(len(busted_segs), len(ref_segs))

    first_divergence = -1
    for i in range(shared):
        if busted_segs[i] != ref_segs[i]:
            first_divergence = i
            break

    # No mismatch within the shared span; check for a length divergence (a
    # segment appended/removed past the common prefix).
    if first_divergence == -1 and len(busted_segs) != len(ref_segs):
        first_divergence = shared

    if first_divergence == -1:
        # Byte-identical heads — no CLIENT-side divergence to report.
        message = (
            f"PREFIX STABLE: client prefix matches req {ref_tag} byte-for-byte. "
            f"If the cache still missed, it was a server-side eviction. "
            f"{HONESTY_CAVEAT}"
        )
        return SegmentAttribution(
            segment=None,
            reference_request_id=reference_request_id,
            stable_through=_stable_label(busted_segs, len(busted_segs)),
            message=message,
        )

    # Label the diverging segment. Past-the-end divergence (a removed/added
    # block) is reported against whichever side still has the segment.
    if first_divergence < len(busted_segs):
        seg_text = busted_segs[first_divergence]
    elif first_divergence < len(ref_segs):
        seg_text = ref_segs[first_divergence]
    else:  # pragma: no cover — defensive
        seg_text = ""
    label = _segment_label(seg_text, first_divergence)
    stable = _stable_label(busted_segs, first_divergence)

    stable_clause = f"{stable} still stable" if stable else "nothing before it was stable"
    message = (
        f"PREFIX BUST: {label} diverged vs req {ref_tag}; {stable_clause}. "
        f"{HONESTY_CAVEAT}"
    )
    return SegmentAttribution(
        segment=label,
        reference_request_id=reference_request_id,
        stable_through=stable,
        message=message,
    )
