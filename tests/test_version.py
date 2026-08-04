"""Regression test for fix-version-pyproject-stale-0-4-0.

The v0.5.0 fix ``fix-version-string-stale-0-3-0`` was chartered to make
``dscache.__version__`` track the packaged version via
``importlib.metadata.version("dscache")`` so the runtime string could not drift
from the wheel metadata on the next bump. The shipped code only hardcoded the
literal AND never bumped ``pyproject.toml`` / ``VERSION`` / ``CHANGELOG.md``,
so the git-tagged v0.5.0 release built a wheel named ``dscache-0.4.0``: ``pip
show dscache`` reported 0.4.0 while ``dscache version`` printed "dscache 0.5.0",
and the old regression test (which only asserted ``__version__ == "0.5.0"``)
passed *while the package metadata was 0.4.0* — it did not guard the drift it
was written to prevent. These tests pin the invariant the old test missed:
``__version__`` must agree with the packaged metadata (when installed) AND
with the ``pyproject.toml`` / ``VERSION`` sources of truth (always).
"""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

import dscache

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
_VERSION_FILE = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _pyproject_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', _PYPROJECT, re.MULTILINE)
    assert match is not None, "pyproject.toml [project] version field not found"
    return match.group(1)


def test_dunder_version_is_not_a_stale_literal():
    # The stale literals from prior iterations must never return.
    assert dscache.__version__ != "0.3.0"
    assert dscache.__version__ != "0.4.0"
    assert dscache.__version__ != "0.5.0"
    # The target version for this iteration is 0.6.0.
    assert dscache.__version__ == "0.6.0"


def test_dunder_version_matches_packaged_metadata_when_installed():
    # The invariant the original fix missed: ``__version__`` must track the
    # INSTALLED package metadata (which ``pyproject.toml`` drives at build
    # time), not a hand-maintained literal. When dscache is pip-installed
    # (the release path), the two must agree — so bumping ``pyproject.toml``
    # alone updates ``dscache.__version__`` and ``dscache version``. When run
    # from a bare source checkout (no install), there is no metadata and
    # ``__version__`` falls back to the literal, which the pyproject/VERSION
    # agreement test below pins instead.
    try:
        packaged = importlib.metadata.version("dscache")
    except importlib.metadata.PackageNotFoundError:
        return  # source checkout, not installed — covered by the agreement test
    assert dscache.__version__ == packaged, (
        f"runtime __version__={dscache.__version__!r} drifted from the packaged "
        f"metadata {packaged!r} — bump pyproject.toml's `version` (and the VERSION "
        f"file / CHANGELOG) to the release tag, and __init__.py's "
        f"_FALLBACK_VERSION must match"
    )


def test_pyproject_version_file_and_dunder_all_agree():
    # The three sources of truth must never drift apart, regardless of whether
    # the package is installed. pyproject drives the wheel name (release.yml
    # runs `python -m build`); VERSION is the repo's version stamp;
    # __version__ is what `dscache version` prints. If any one lags, ``pip
    # install dscache==<tag>`` cannot resolve while ``dscache version`` prints
    # a different number — the exact drift class fix-version-pyproject-stale
    # closes.
    pyproject_v = _pyproject_version()
    assert pyproject_v == _VERSION_FILE, (
        f"pyproject.toml version={pyproject_v!r} != VERSION file={_VERSION_FILE!r}"
    )
    assert dscache.__version__ in (pyproject_v, _VERSION_FILE), (
        f"__version__={dscache.__version__!r} drifted from pyproject/VERSION "
        f"={pyproject_v!r}"
    )


def test_dunder_version_is_exported_in_all():
    # __version__ is part of the public API surface declared in __all__.
    assert "__version__" in dscache.__all__
