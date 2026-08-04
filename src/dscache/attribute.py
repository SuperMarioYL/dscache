"""Byte-level prefix-divergence attribution.

When the profiler detects a prefix bust against its most-recent-HIT reference,
this module diffs the two *serialized request heads* at BYTE granularity —
naming the **first** diverging segment AND the exact diverging byte offset
within it, e.g.::

    PREFIX BUST: tools[3] byte offset 412 diverged vs req r17; segments[0..2] still stable.

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
the same ``\\n`` boundaries the wrapper writes; the byte offset is then located
*within* the first diverging segment by comparing its UTF-8 bytes against the
reference segment's bytes.

v0.6.0 deepened the diff from segment-level to byte granularity
(``feat-byte-level-prefix-divergence-attribution``), folding cacheguard's
byte-level prefix-mutation linter into dscache's OWN attribute path as
DETECTION-only deepening. The cacheguard prefix-MUTATION capability (rewriting
the prefix to stabilize cache) is explicitly DROPPED, consistent with dscache's
"suggest only, never mutate" thesis and the out-of-scope standalone-linter
ban. The honesty caveat is unchanged: byte-level attribution explains a
client-caused bust at finer granularity, not a server-side eviction.
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
    """The first diverging segment (and byte) between a bust and its reference.

    v0.6.0 deepened the diff from segment-level to byte granularity: the
    ``byte_offset`` field names the exact diverging byte within the first
    diverging segment, so a bust tells the user *where* in the segment the
    client prefix broke, not just *which* segment.
    """

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
    #: 0-based BYTE offset, *within the first diverging segment*, of the first
    #: byte where the busted request's serialized head diverges from the
    #: reference's. ``None`` when no client-side divergence was found (clean
    #: diff / server-side eviction). Counts UTF-8 bytes of the segment text,
    #: so a non-ASCII prompt still reports a stable byte-accurate span
    #: (feat-byte-level-prefix-divergence-attribution).
    byte_offset: Optional[int] = None

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


def _first_diverging_byte_offset(busted_seg: str, ref_seg: str) -> Optional[int]:
    """0-based BYTE offset of the first diverging byte within a segment pair.

    Counts UTF-8 bytes of the segment text (not characters), so a non-ASCII
    prompt still reports a stable, byte-accurate span. Returns the offset of
    the first byte where the two segments differ; if one segment is a strict
    byte-prefix of the other (a length divergence — a segment that grew or
    shrank), returns the length of the shared byte prefix (the offset where
    the appended/removed tail begins). Returns ``None`` only when the two
    segments are byte-identical (no divergence to locate).

    (feat-byte-level-prefix-divergence-attribution: deepen the diff from
    segment-level to byte granularity.)
    """
    b_busted = busted_seg.encode("utf-8")
    b_ref = ref_seg.encode("utf-8")
    shared = min(len(b_busted), len(b_ref))
    for i in range(shared):
        if b_busted[i] != b_ref[i]:
            return i
    if len(b_busted) == len(b_ref):
        # Byte-identical — no divergence to locate within this segment.
        return None
    # One is a strict byte-prefix of the other: the divergence starts at the
    # first byte past the shared prefix (the appended/removed tail).
    return shared


def attribute_bust(
    busted_sample: Optional[str],
    reference_sample: Optional[str],
    reference_request_id: Optional[str],
) -> SegmentAttribution:
    """Diff two serialized request heads and name the first diverging byte.

    v0.6.0 deepened the diff from segment-level to BYTE granularity
    (``feat-byte-level-prefix-divergence-attribution``): the result names the
    first diverging SEGMENT (``tools[3]`` / ``messages[0]`` / ``system``) AND
    the exact diverging BYTE offset within it, so a bust tells the user
    *where* in the segment the client prefix broke, not just *which* segment.

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
        ``segment`` is the label of the first diverging segment and
        ``byte_offset`` is the 0-based byte offset of the first diverging byte
        within that segment; both are ``None`` when the two heads are
        byte-identical over their shared length (a clean client-side diff —
        the bust is then attributable to server-side eviction, which dscache
        cannot observe).

    This is **detect-and-attribute only**: it never mutates either sample.
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
            byte_offset=None,
        )

    # Label the diverging segment. Past-the-end divergence (a removed/added
    # block) is reported against whichever side still has the segment.
    busted_seg_text = (
        busted_segs[first_divergence] if first_divergence < len(busted_segs) else ""
    )
    ref_seg_text = (
        ref_segs[first_divergence] if first_divergence < len(ref_segs) else ""
    )
    seg_text = busted_seg_text or ref_seg_text
    label = _segment_label(seg_text, first_divergence)
    stable = _stable_label(busted_segs, first_divergence)

    # Byte-level deepening: locate the first diverging BYTE within the
    # diverging segment pair (feat-byte-level-prefix-divergence-attribution).
    # When the segment exists on BOTH sides, diff its UTF-8 bytes against the
    # reference segment's bytes; when it exists on only one side (a segment
    # appended/removed past the common segment prefix), the divergence starts
    # at byte 0 of that segment.
    if busted_seg_text and ref_seg_text:
        byte_offset = _first_diverging_byte_offset(busted_seg_text, ref_seg_text)
        if byte_offset is None:  # pragma: no cover — defensive
            # The two segment texts are byte-identical; should not happen for a
            # known-diverging segment, but treat the whole segment as the span.
            byte_offset = 0
    else:
        byte_offset = 0

    stable_clause = f"{stable} still stable" if stable else "nothing before it was stable"
    message = (
        f"PREFIX BUST: {label} byte offset {byte_offset} diverged vs req "
        f"{ref_tag}; {stable_clause}. {HONESTY_CAVEAT}"
    )
    return SegmentAttribution(
        segment=label,
        reference_request_id=reference_request_id,
        stable_through=stable,
        message=message,
        byte_offset=byte_offset,
    )
