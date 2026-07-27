"""Regression test for fix-version-string-stale-0-3-0.

``dscache.__version__`` was stuck at the literal ``"0.3.0"`` across the v0.4.0
and v0.5.0 iterations while every other source of truth (``pyproject.toml``,
the ``VERSION`` file, ``CHANGELOG.md``, the published build metadata) moved on.
The ``dscache version`` command (``src/dscache/cli.py`` prints
``f"dscache {__version__}"``) therefore reported "dscache 0.3.0" for a 0.4.0/0.5.0
install, misleading bug reporters and any version-gated logic reading
``dscache.__version__``. Pin the corrected target value so the stale literal
cannot return unnoticed.
"""

from __future__ import annotations

import dscache


def test_dunder_version_is_target_not_stale_literal():
    # The stale value from before the fix must never return.
    assert dscache.__version__ != "0.3.0"
    # The target version for this iteration is 0.5.0.
    assert dscache.__version__ == "0.5.0"


def test_dunder_version_is_exported_in_all():
    # __version__ is part of the public API surface declared in __all__.
    assert "__version__" in dscache.__all__
