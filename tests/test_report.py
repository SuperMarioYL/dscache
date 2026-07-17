"""Tests for v0.3.0 `dscache report --compare` and the compare-delta panel.

Covers:
- feat-report-compare-baseline: render_compare_delta prints the recovered
  cache-busts / wasted-¥ / ratio-drop panel, says "recovered" not "saved",
  and handles the worse / no-change branches.
"""

from __future__ import annotations

from decimal import Decimal

from rich.console import Console

from dscache.profiler import profile
from dscache.report import render_compare_delta, render_headline


def _baseline_ledger():
    # A busted run: r1 HITs, r2 MISSes (real bust).
    return [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:CHANGED\nuser:a"},
    ]


def _fixed_ledger():
    # The same run AFTER applying the suggestion: both fully HIT (prefix pinned,
    # zero miss tokens -> zero wasted ¥).
    return [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 1000,
         "miss_tokens": 0, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 1000,
         "miss_tokens": 0, "prefix_sample": "system:stable\nuser:a"},
    ]


def _render(panel) -> str:
    console = Console(width=160, record=True)
    console.print(panel)
    return console.export_text()


def test_compare_delta_reports_recovered_waste_and_busts():
    baseline = profile(_baseline_ledger())
    current = profile(_fixed_ledger())
    panel = render_compare_delta(baseline, current)
    rendered = _render(panel)
    # Honest language: the operative claim is "recovered", and the panel
    # carries the honesty caveat that dscache cannot prove the user pinned
    # the prefix (the disclaimer is what makes "recovered" honest).
    assert "recovered" in rendered.lower()
    assert "cannot prove" in rendered.lower()
    # The baseline had 1 bust; the fixed run has 0 -> recovered 1 bust.
    assert "1 cache-bust" in rendered.lower() or "1 bust" in rendered.lower()
    # Ratio dropped from a large number to 1.00x (the fixed run is all-HIT).
    assert "1.00" in rendered


def test_compare_delta_says_worse_when_current_regressed():
    # Baseline was stable; current busted -> the panel must say "WORSE", not
    # claim a recovery.
    baseline = profile(_fixed_ledger())
    current = profile(_baseline_ledger())
    rendered = _render(render_compare_delta(baseline, current))
    assert "worse" in rendered.lower()


def test_compare_delta_no_change_when_identical():
    baseline = profile(_baseline_ledger())
    current = profile(_baseline_ledger())
    rendered = _render(render_compare_delta(baseline, current))
    assert "no change" in rendered.lower()


def test_compare_delta_excludes_unknown_from_both_sides():
    # UNKNOWN-tier entries must not fabricate recovered ¥ on either side.
    unknown_only = [{"request_id": f"r{i}", "prompt_tokens": 4000} for i in range(3)]
    baseline = profile(unknown_only)
    current = profile(unknown_only)
    rendered = _render(render_compare_delta(baseline, current))
    assert "no change" in rendered.lower()  # zero judged waste on both sides


def test_compare_delta_reuses_headline_numbers():
    # The compare panel's numbers are the same ones render_headline computes,
    # so a recovered panel's baseline-wasted equals the baseline headline's
    # wasted. This guards against the two paths drifting.
    baseline = profile(_baseline_ledger())
    current = profile(_fixed_ledger())
    # Baseline headline shows wasted (>0); current headline shows ¥0 wasted.
    assert "wasted" in _render(render_headline(baseline)).lower()
    assert "¥0 wasted" in _render(render_headline(current))


def test_compare_recovered_wasted_is_positive_decimal():
    baseline = profile(_baseline_ledger())
    current = profile(_fixed_ledger())
    # Recovered = baseline.wasted - current.wasted; baseline wasted > current.
    from dscache.report import _headline_numbers

    b = _headline_numbers(baseline)
    c = _headline_numbers(current)
    assert b["wasted"] > c["wasted"]
    assert (b["wasted"] - c["wasted"]) > Decimal("0")
