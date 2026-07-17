"""dscache — a prefix-cache profit-and-loss layer for DeepSeek coding agents.

Wrap your existing DeepSeek (OpenAI-compatible) client in two lines and dscache
transparently records each response's context-cache usage to a local ledger.
Then ``dscache report`` shows, per request, whether the call HIT / PARTIAL /
MISS the cached-input discount tier — and how much money the misses cost.

Quickstart::

    import dscache
    from openai import OpenAI

    client = dscache.wrap(OpenAI(base_url="https://api.deepseek.com", api_key=...))
    # ... run your agent loop as usual ...
    # then:  dscache report
"""

from __future__ import annotations

from .attribute import SegmentAttribution, attribute_bust
from .profiler import CacheLedgerEntry, Tier, load_ledger, profile
from .wrapper import DEFAULT_LEDGER_PATH, wrap

__all__ = [
    "wrap",
    "profile",
    "load_ledger",
    "CacheLedgerEntry",
    "Tier",
    "SegmentAttribution",
    "attribute_bust",
    "DEFAULT_LEDGER_PATH",
    "__version__",
]

__version__ = "0.3.0"
