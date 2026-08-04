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

import importlib.metadata as _metadata

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

# ``__version__`` is derived at runtime from the INSTALLED package metadata
# (``importlib.metadata.version("dscache")``, which reads the ``version`` field
# ``pyproject.toml`` ships at build time) so the runtime string tracks the
# packaged version and cannot drift from it on the next bump (fix
# fix-version-pyproject-stale-0-4-0). The literal fallback below only applies
# when the package is imported from a bare source checkout that was never
# installed (e.g. ``PYTHONPATH=src`` with no ``pip install``) — in that case
# there is no metadata to read, and the literal is the only source of truth,
# kept in sync with ``pyproject.toml`` / ``VERSION`` / ``CHANGELOG.md``
# manually. When installed (the release path the release.yml workflow drives
# via ``python -m build``), the metadata wins, so bumping ``pyproject.toml``
# alone updates ``dscache.__version__`` and ``dscache version`` automatically.
_FALLBACK_VERSION = "0.6.0"
try:
    __version__ = _metadata.version("dscache")
except _metadata.PackageNotFoundError:  # source checkout, not installed
    __version__ = _FALLBACK_VERSION
