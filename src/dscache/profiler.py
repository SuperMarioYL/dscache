"""Core primitive: the per-request cache-tier ledger entry + prefix fingerprint.

A :class:`CacheLedgerEntry` is the atom dscache reasons about. The reusable
verb lives in :func:`profile`: given a sequence of raw ledger records, derive
each request's cache tier, compute a rolling prefix fingerprint, price the call
at DeepSeek's two-tier cache pricing, and (m2) detect prefix-bust events.

DeepSeek's chat-completions ``usage`` object is documented to expose
``prompt_cache_hit_tokens`` and ``prompt_cache_miss_tokens``. These fields are
UNVERIFIED on the build machine (no API key), so every reader here degrades
gracefully: a missing field is treated as ``None`` and the entry is tagged
``UNKNOWN`` rather than crashing the run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional


class Tier(str, Enum):
    """Cache-discount tier derived from the cached/prompt token ratio."""

    HIT = "HIT"
    PARTIAL = "PARTIAL"
    MISS = "MISS"
    #: Returned when DeepSeek did not surface the cache usage fields at all.
    UNKNOWN = "UNKNOWN"


# DeepSeek two-tier context-cache input pricing, in CNY per 1M tokens.
# Source: DeepSeek API pricing (deepseek-chat standard input).
# These are the documented public list prices; override via price_* args if the
# provider changes them. Output tokens are not part of the cache-discount story
# and are intentionally excluded from the dscache money model.
DEEPSEEK_CACHE_HIT_PRICE_PER_1M = Decimal("0.5")
DEEPSEEK_CACHE_MISS_PRICE_PER_1M = Decimal("2.0")

# Tier thresholds on the cached/prompt ratio.
HIT_THRESHOLD = 0.90
MISS_THRESHOLD = 0.10

# Length (in characters) of the leading prompt span we fingerprint for stability.
PREFIX_SPAN_CHARS = 2048


@dataclass
class CacheLedgerEntry:
    """One profiled request — the dscache primitive.

    ``cached_tokens`` / ``miss_tokens`` come straight from DeepSeek ``usage``;
    either may be ``None`` when the provider omitted them (handled defensively).
    """

    request_id: str
    prompt_tokens: int
    cached_tokens: Optional[int]
    miss_tokens: Optional[int]
    tier: Tier = Tier.UNKNOWN
    prefix_fingerprint: Optional[str] = None
    busted_against: Optional[str] = None
    cost_actual: Decimal = Decimal("0")
    cost_ideal: Decimal = Decimal("0")
    model: str = "deepseek-chat"
    timestamp: Optional[float] = None
    # Raw prefix sample retained only in-memory for reorder analysis; never
    # serialized verbatim to keep the ledger small and prompt-content-free.
    _prefix_sample: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def wasted(self) -> Decimal:
        """Money lost on this request versus the all-cached ideal."""
        return self.cost_actual - self.cost_ideal

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_prefix_sample", None)
        d["tier"] = self.tier.value
        d["cost_actual"] = str(self.cost_actual)
        d["cost_ideal"] = str(self.cost_ideal)
        return d


def derive_tier(prompt_tokens: int, cached_tokens: Optional[int]) -> Tier:
    """Classify a request by its cached/prompt ratio.

    Defensive: if ``cached_tokens`` is unknown or the prompt is empty we cannot
    judge the discount tier, so we return :attr:`Tier.UNKNOWN`.
    """
    if cached_tokens is None or prompt_tokens <= 0:
        return Tier.UNKNOWN
    ratio = cached_tokens / prompt_tokens
    if ratio >= HIT_THRESHOLD:
        return Tier.HIT
    if ratio <= MISS_THRESHOLD:
        return Tier.MISS
    return Tier.PARTIAL


def fingerprint_prefix(prefix_text: Optional[str], span: int = PREFIX_SPAN_CHARS) -> Optional[str]:
    """Rolling hash of the leading stable span of a prompt.

    Two requests that share a byte-identical leading ``span`` share a
    fingerprint — that is exactly the prefix DeepSeek can serve from cache.
    Returns ``None`` when no prefix text was captured.
    """
    if not prefix_text:
        return None
    head = prefix_text[:span].encode("utf-8")
    return hashlib.sha256(head).hexdigest()[:16]


def price_request(
    cached_tokens: Optional[int],
    miss_tokens: Optional[int],
    prompt_tokens: int,
    *,
    hit_price_per_1m: Decimal = DEEPSEEK_CACHE_HIT_PRICE_PER_1M,
    miss_price_per_1m: Decimal = DEEPSEEK_CACHE_MISS_PRICE_PER_1M,
) -> tuple[Decimal, Decimal]:
    """Return ``(cost_actual, cost_ideal)`` for one request, in CNY.

    ``cost_actual`` prices the miss tokens at the full (cache-miss) rate and the
    cached tokens at the discounted rate. ``cost_ideal`` is the counterfactual
    where the *entire* prompt had stayed in the cached tier (a byte-stable
    prefix). The gap between them is the money a prefix-bust costs.

    Degrades gracefully: when the cache split is unknown we fall back to pricing
    the whole prompt at the miss rate for ``cost_actual`` and at the hit rate for
    ``cost_ideal`` — a conservative but non-crashing estimate.
    """
    hit_rate = hit_price_per_1m / Decimal(1_000_000)
    miss_rate = miss_price_per_1m / Decimal(1_000_000)

    if cached_tokens is None or miss_tokens is None:
        actual = Decimal(prompt_tokens) * miss_rate
        ideal = Decimal(prompt_tokens) * hit_rate
        return _q(actual), _q(ideal)

    actual = Decimal(cached_tokens) * hit_rate + Decimal(miss_tokens) * miss_rate
    total = cached_tokens + miss_tokens
    ideal = Decimal(total) * hit_rate
    return _q(actual), _q(ideal)


def _q(value: Decimal) -> Decimal:
    """Quantize a CNY amount to 6 decimal places (sub-fen precision)."""
    return value.quantize(Decimal("0.000001"))


def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort int coercion that never raises on bad provider data."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def entry_from_record(record: dict[str, Any]) -> CacheLedgerEntry:
    """Build a (pre-profiled) ledger entry from one raw ledger record.

    A raw record is what :mod:`dscache.wrapper` writes to ``ledger.jsonl``.
    Unknown / malformed fields degrade to ``None`` rather than raising.
    """
    prompt_tokens = _coerce_int(record.get("prompt_tokens")) or 0
    cached_tokens = _coerce_int(record.get("cached_tokens"))
    miss_tokens = _coerce_int(record.get("miss_tokens"))

    # If only one side of the split is present, infer the other from the total.
    if cached_tokens is not None and miss_tokens is None and prompt_tokens:
        miss_tokens = max(prompt_tokens - cached_tokens, 0)
    if miss_tokens is not None and cached_tokens is None and prompt_tokens:
        cached_tokens = max(prompt_tokens - miss_tokens, 0)

    return CacheLedgerEntry(
        request_id=str(record.get("request_id", "")),
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        miss_tokens=miss_tokens,
        model=str(record.get("model", "deepseek-chat")),
        timestamp=record.get("timestamp"),
        _prefix_sample=record.get("prefix_sample"),
    )


def profile(records: Iterable[dict[str, Any]]) -> list[CacheLedgerEntry]:
    """The reusable verb: turn raw ledger records into profiled entries.

    For each record we derive the tier, fingerprint the prefix, price the call,
    and (m1-light, full detection lands in m2) tag the prior cached request whose
    stable prefix it should have matched. m2's :mod:`dscache.reorder` consumes
    the ``busted_against`` links to compute concrete reorder suggestions.
    """
    entries: list[CacheLedgerEntry] = []
    # Map of fingerprint -> request_id of the first request that established it.
    seen_prefixes: dict[str, str] = {}
    last_request_id: Optional[str] = None

    for record in records:
        entry = entry_from_record(record)
        entry.tier = derive_tier(entry.prompt_tokens, entry.cached_tokens)
        entry.prefix_fingerprint = fingerprint_prefix(entry._prefix_sample)
        entry.cost_actual, entry.cost_ideal = price_request(
            entry.cached_tokens, entry.miss_tokens, entry.prompt_tokens
        )

        fp = entry.prefix_fingerprint
        if fp is not None:
            if fp in seen_prefixes:
                # Same stable prefix as before — good, this is a cache-friendly call.
                pass
            else:
                # New prefix. If we had a prior request and this one missed the
                # cache, mark it as busted against the most recent request so m2
                # can suggest a reorder back to a stable span.
                if last_request_id is not None and entry.tier in (Tier.MISS, Tier.PARTIAL):
                    entry.busted_against = last_request_id
                seen_prefixes[fp] = entry.request_id

        entries.append(entry)
        last_request_id = entry.request_id

    return entries


def load_ledger(path: str | Path) -> list[dict[str, Any]]:
    """Read raw ledger records from a JSONL file.

    Malformed lines are skipped (defensive against a partially-written ledger
    from an interrupted agent run) rather than aborting the whole report.
    """
    p = Path(path)
    if not p.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _iter_profiled(path: str | Path) -> Iterator[CacheLedgerEntry]:
    yield from profile(load_ledger(path))
