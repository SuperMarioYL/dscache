"""Transparent client wrapper.

``dscache.wrap(client)`` returns a thin proxy around the user's DeepSeek /
OpenAI-compatible client. It intercepts ``chat.completions.create`` responses,
reads the context-cache usage fields, and appends a record to a local
``.dscache/ledger.jsonl``. It is **pure pass-through**: the request is never
mutated and the original response object is returned unchanged. If anything in
the accounting path fails, the user's call still succeeds — instrumentation
must never break the agent loop.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

DEFAULT_LEDGER_PATH = Path(".dscache") / "ledger.jsonl"

# How much of the leading prompt text we sample for prefix fingerprinting.
# Kept small and never reproduced in reports — it exists only so the profiler
# can tell whether two requests shared a byte-stable prefix.
_PREFIX_SAMPLE_CHARS = 2048

_write_lock = threading.Lock()


def wrap(client: Any, *, ledger_path: str | os.PathLike[str] | None = None) -> Any:
    """Wrap an OpenAI-compatible client so each completion is profiled.

    Parameters
    ----------
    client:
        Any object exposing ``client.chat.completions.create(...)`` (the OpenAI
        Python SDK shape, which DeepSeek's API is compatible with).
    ledger_path:
        Where to append ledger records. Defaults to ``.dscache/ledger.jsonl``
        in the current working directory.

    Returns
    -------
    A proxy that forwards every attribute access to ``client`` but transparently
    instruments ``chat.completions.create``.
    """
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    return _ClientProxy(client, path)


class _ClientProxy:
    """Attribute-forwarding proxy whose only special-case is ``.chat``."""

    def __init__(self, client: Any, ledger_path: Path) -> None:
        self.__dict__["_client"] = client
        self.__dict__["_ledger_path"] = ledger_path

    @property
    def chat(self) -> "_ChatProxy":
        return _ChatProxy(self._client.chat, self._ledger_path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["_client"], name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.__dict__["_client"], name, value)


class _ChatProxy:
    def __init__(self, chat: Any, ledger_path: Path) -> None:
        self._chat = chat
        self._ledger_path = ledger_path

    @property
    def completions(self) -> "_CompletionsProxy":
        return _CompletionsProxy(self._chat.completions, self._ledger_path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class _CompletionsProxy:
    def __init__(self, completions: Any, ledger_path: Path) -> None:
        self._completions = completions
        self._ledger_path = ledger_path

    def create(self, *args: Any, **kwargs: Any) -> Any:
        response = self._completions.create(*args, **kwargs)
        # Accounting must never break the caller's loop.
        try:
            record = _build_record(kwargs, response)
            if record is not None:
                append_record(self._ledger_path, record)
        except Exception:  # noqa: BLE001 — instrumentation is best-effort
            pass
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)


def _build_record(request_kwargs: dict[str, Any], response: Any) -> Optional[dict[str, Any]]:
    """Extract a ledger record from a completion response.

    Reads ``usage.prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens``
    defensively — these DeepSeek fields are unverified and may be absent on
    other providers, in which case they are recorded as ``None``.
    """
    usage = _get(response, "usage")
    prompt_tokens = _get_int(usage, "prompt_tokens")
    cached_tokens = _get_int(usage, "prompt_cache_hit_tokens")
    miss_tokens = _get_int(usage, "prompt_cache_miss_tokens")

    request_id = _get(response, "id") or f"req_{uuid.uuid4().hex[:12]}"
    model = _get(response, "model") or request_kwargs.get("model") or "deepseek-chat"

    return {
        "request_id": str(request_id),
        "timestamp": time.time(),
        "model": str(model),
        "prompt_tokens": prompt_tokens if prompt_tokens is not None else 0,
        "cached_tokens": cached_tokens,
        "miss_tokens": miss_tokens,
        "prefix_sample": _prefix_sample(request_kwargs),
    }


def _prefix_sample(request_kwargs: Any) -> Optional[str]:
    """Serialize the leading request head into a stable prefix sample.

    DeepSeek's prefix cache keys on the full serialized request head, not just
    the messages. For coding agents that head is dominated by a large, often
    *reordered* ``tools`` array — so two calls with identical leading messages
    but a shuffled tool list have genuinely different cache keys. We therefore
    serialize ``tools`` / ``tool_choice`` / ``response_format`` *ahead* of the
    leading message text, then cap at ``_PREFIX_SAMPLE_CHARS``.

    Each segment is emitted on its own ``\\n`` line so :mod:`dscache.attribute`
    can recover segment granularity (``tools[i]``, ``system``, ``messages[i]``).
    Message *content* is serialized via the same ``_serialize_value``
    (``json.dumps``) path already used for tools — which escapes any literal
    ``\\n`` in the content — before joining, so a multi-line system/user
    prompt (the common case for coding agents) no longer shatters
    ``attribute._split_segments`` into N spurious ``segment[K]`` labels and the
    advertised "which message index" granularity is preserved. Tool blocks were
    already safe via ``json.dumps``; only raw message content needed it (fix
    fix-multiline-content-breaks-segment-attribution; the fingerprint-format
    bump is a v0.4.0 ledger-contract change, samples are per-run).
    The cap is applied at SEGMENT BOUNDARIES across all segments: a segment
    that would overflow the remaining budget is never appended, so no segment
    is ever truncated mid-way (fix
    fix-prefix-sample-truncates-mid-segment). This matters for coding agents
    whose tool list dominates the budget: the sample fills with whole tool
    blocks up to the cap, and a divergence in a later tool or in the leading
    message past the tool head is simply not sampled (still a faithful lower
    bound on the real cache key, as the v0.2.0 honesty caveat already states)
    rather than corrupting the fingerprint with a half-segment stub.

    Returns ``None`` when nothing usable was found.
    """
    if not isinstance(request_kwargs, dict):
        return None

    parts: list[str] = []
    budget = _PREFIX_SAMPLE_CHARS

    def _append(segment: str) -> bool:
        """Append a segment if it fits the remaining budget; else stop.

        Returns True if the segment was appended, False if the budget is
        exhausted (caller should stop adding further segments).
        """
        nonlocal budget
        # +1 for the "\n" separator that joins segments.
        cost = len(segment) + (1 if parts else 0)
        if cost > budget:
            return False
        parts.append(segment)
        budget -= cost
        return True

    # 1. Tool definitions come first — they sit at the head of DeepSeek's real
    #    cache key, so a reordered tool list must change the fingerprint.
    tools = request_kwargs.get("tools")
    if isinstance(tools, (list, tuple)):
        for i, tool in enumerate(tools):
            seg = f"tools[{i}]:{_serialize_tool(tool)}"
            if not _append(seg):
                break

    tool_choice = request_kwargs.get("tool_choice")
    if tool_choice is not None:
        _append(f"tool_choice:{_serialize_value(tool_choice)}")

    response_format = request_kwargs.get("response_format")
    if response_format is not None:
        _append(f"response_format:{_serialize_value(response_format)}")

    # 2. Leading messages, after the tool head.
    messages = request_kwargs.get("messages")
    if isinstance(messages, (list, tuple)):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", ""))
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal content blocks — keep only text parts.
                content = "".join(
                    str(block.get("text", "")) for block in content if isinstance(block, dict)
                )
            # Serialize content via _serialize_value (json.dumps) — the same
            # path used for tools — so a literal "\n" in the content is escaped
            # and "\n" stays an unambiguous segment separator. Otherwise a
            # multi-line system/user prompt would shatter attribute._split_segments
            # into N spurious "segment[K]" labels (fix
            # fix-multiline-content-breaks-segment-attribution).
            if not _append(f"{role}:{_serialize_value(content)}"):
                break

    return "\n".join(parts) if parts else None


def _serialize_tool(tool: Any) -> str:
    """Stably serialize one tool definition for the prefix sample.

    Preserves the tool's *positional* order (we want a reorder to be visible) but
    serializes each tool's keys sorted, so an equivalent tool block produces an
    identical string regardless of dict insertion order.
    """
    return _serialize_value(tool)


def _serialize_value(value: Any) -> str:
    """Compact, key-sorted JSON serialization; falls back to ``str``."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def append_record(ledger_path: str | os.PathLike[str], record: dict[str, Any]) -> None:
    """Append one record to the JSONL ledger, creating parent dirs as needed."""
    path = Path(ledger_path)
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _get(obj: Any, name: str) -> Any:
    """Read ``name`` from an object whether it's an attr or a dict key."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _get_int(obj: Any, name: str) -> Optional[int]:
    value = _get(obj, name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
