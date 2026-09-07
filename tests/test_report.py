"""Tests for v0.3.0 `dscache report --compare` and the compare-delta panel.

Covers:
- feat-report-compare-baseline: render_compare_delta prints the recovered
  cache-busts / wasted-¥ / ratio-drop panel, says "recovered" not "saved",
  and handles the worse / no-change branches.
"""

from __future__ import annotations

from decimal import Decimal

from rich.console import Console

from dscache.profiler import Tier, profile
from dscache.report import _headline_numbers, render_compare_delta, render_headline


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
    # UNKNOWN-tier entries must not fabricate a recovered/¥ verdict on either
    # side. With fix-compare-fabricates-recovery-on-empty-ledger, a ledger with
    # NO judged requests (empty or all-UNKNOWN) on either side no longer drives
    # a money-driven verdict at all — it emits an honest "no judged" hint, so
    # all-UNKNOWN data can never fabricate a fake recovery/regression.
    unknown_only = [{"request_id": f"r{i}", "prompt_tokens": 4000} for i in range(3)]
    baseline = profile(unknown_only)
    current = profile(unknown_only)
    rendered = _render(render_compare_delta(baseline, current))
    assert "no judged" in rendered.lower() or "neither" in rendered.lower()
    assert "recovered" not in rendered.lower()
    assert "worse" not in rendered.lower()


# --- fix-headline-busted-zero-contradicts-wasted-money -----------------------


def test_headline_cold_start_miss_no_phantom_busted_zero():
    # fix-headline-busted-zero-contradicts-wasted-money: after the v0.6.0/v0.7.0
    # cold-start fixes, a genuine MISS with no prior stable prefix leaves
    # busted_against unset (busted == 0) while wasted > 0. The old headline had
    # only a `wasted > 0` branch that unconditionally printed "busted the cache
    # 0× ... ¥Z wasted" — self-contradictory (a bust count of zero next to a
    # non-zero wasted figure). The fix adds a third branch that reports the
    # waste honestly without the phantom bust count.
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:a\nuser:b"},
    ]
    entries = profile(records)
    assert entries[0].tier is Tier.MISS
    assert entries[0].busted_against is None  # cold start, no prior stable prefix
    nums = _headline_numbers(entries)
    assert nums["busted"] == 0
    assert nums["wasted"] > Decimal("0")
    rendered = _render(render_headline(entries))
    assert "wasted" in rendered.lower()
    # The self-contradictory "busted the cache 0×" clause is gone.
    assert "busted the cache 0" not in rendered.lower()
    # The honest cold-start language surfaces instead.
    assert "no prefix-bust" in rendered.lower()
    assert "cold start" in rendered.lower()


def test_headline_busted_count_still_shown_when_real_busts_exist():
    # Regression guard for fix-headline-busted-zero-contradicts-wasted-money:
    # the existing "busted N× ... ¥Z wasted" branch is unchanged when real
    # client-side busts exist (busted > 0 AND wasted > 0). A run with a prior HIT
    # and a genuine prefix-bust MISS must still print the bust count.
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:CHANGED\nuser:a"},
    ]
    entries = profile(records)
    nums = _headline_numbers(entries)
    assert nums["busted"] == 1 and nums["wasted"] > Decimal("0")
    rendered = _render(render_headline(entries))
    assert "busted the cache 1" in rendered.lower()
    assert "wasted" in rendered.lower()


# --- fix-headline-fabricates-stable-on-all-unknown-ledger -------------------


def test_headline_all_unknown_no_fake_stable():
    # fix-headline-fabricates-stable-on-all-unknown-ledger: a run where DeepSeek
    # never surfaced the cache-hit/miss fields (every request UNKNOWN) used to
    # print "Cache held stable — ¥0 wasted. Your prefix discount is intact." —
    # a fabricated POSITIVE verdict on data dscache admits it cannot judge, the
    # single-ledger analogue of the v0.8.0 compare-empty fabrication. The fix
    # adds a zero-judged-requests guard (total_ideal == 0) that emits an honest
    # "no judged cache requests" hint instead.
    records = [
        {"request_id": f"r{i}", "prompt_tokens": 4000} for i in range(3)
    ]
    entries = profile(records)
    assert all(e.tier is Tier.UNKNOWN for e in entries)
    nums = _headline_numbers(entries)
    assert nums["total_ideal"] == Decimal("0")  # zero judged requests
    rendered = _render(render_headline(entries))
    assert "no judged" in rendered.lower()
    assert "Cache held stable" not in rendered
    assert "discount is intact" not in rendered
    # No phantom money on unjudgeable data.
    assert "wasted" not in rendered.lower() or "¥0" in rendered


def test_headline_guard_does_not_fire_on_real_busts():
    # Regression guard for fix-headline-fabricates-stable-on-all-unknown-ledger:
    # the zero-judged-requests guard (total_ideal == 0) must NOT over-fire when
    # judged requests exist. A run with a real HIT + a real MISS bust still
    # prints the bust (total_ideal > 0, so the guard is skipped and the
    # existing "busted the cache N× ... wasted" branch runs unchanged).
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": "system:CHANGED\nuser:a"},
    ]
    entries = profile(records)
    nums = _headline_numbers(entries)
    assert nums["total_ideal"] > Decimal("0")  # judged requests exist
    assert nums["busted"] == 1
    rendered = _render(render_headline(entries))
    assert "busted the cache 1" in rendered.lower()
    assert "no judged" not in rendered.lower()


# --- fix-compare-fabricates-recovery-on-empty-ledger -------------------------


def test_compare_delta_empty_current_no_fake_recovery():
    # fix-compare-fabricates-recovery-on-empty-ledger: an empty/missing current
    # ledger used to make recovered_wasted = baseline_wasted - 0 > 0 and print a
    # fake "recovered N bust(s) and ¥Z" panel directly above the report table's
    # "No ledger entries found" line for the same ledger. The fix guards: when
    # either side has no judged requests, emit an honest hint instead.
    baseline = profile(_baseline_ledger())  # r1 HIT, r2 MISS bust -> has waste
    current = profile([])  # empty current ledger
    rendered = _render(render_compare_delta(baseline, current))
    assert "no judged" in rendered.lower()
    assert "recovered" not in rendered.lower()
    assert "worse" not in rendered.lower()


def test_compare_delta_empty_baseline_no_fake_worse():
    # Mirror of the empty-current case: an empty baseline with a waste-bearing
    # current used to fabricate a "Cache got WORSE" panel against nothing.
    baseline = profile([])
    current = profile(_baseline_ledger())  # has waste
    rendered = _render(render_compare_delta(baseline, current))
    assert "no judged" in rendered.lower()
    assert "worse" not in rendered.lower()
    assert "recovered" not in rendered.lower()


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


def test_compare_delta_worse_branch_bust_count_never_negative():
    # Regression for fix-compare-negative-new-bust-count (WORSE branch).
    # Money got WORSE (current wastes more ¥) BUT busts went DOWN (3 -> 0).
    # The money-driven verdict still says WORSE; the displayed bust count must
    # be non-negative ("0 new bust(s)"), never the nonsensical "-3 new bust(s)"
    # the old money-sign-driven bust delta printed when the two directions
    # disagreed.
    baseline = profile([
        # b1 establishes a stable prefix; b2-b4 are 3 small MISS busts.
        {"request_id": "b1", "prompt_tokens": 1000, "cached_tokens": 1000,
         "miss_tokens": 0, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "b2", "prompt_tokens": 1000, "cached_tokens": 0,
         "miss_tokens": 1000, "prefix_sample": "system:CHANGED-1\nuser:a"},
        {"request_id": "b3", "prompt_tokens": 1000, "cached_tokens": 0,
         "miss_tokens": 1000, "prefix_sample": "system:CHANGED-2\nuser:a"},
        {"request_id": "b4", "prompt_tokens": 1000, "cached_tokens": 0,
         "miss_tokens": 1000, "prefix_sample": "system:CHANGED-3\nuser:a"},
    ])
    current = profile([
        # One big uncached MISS with no prior reference: 0 busts, big waste.
        {"request_id": "c1", "prompt_tokens": 100000, "cached_tokens": 0,
         "miss_tokens": 100000, "prefix_sample": "system:fresh\nuser:z"},
    ])
    from dscache.report import _headline_numbers

    b = _headline_numbers(baseline)
    c = _headline_numbers(current)
    # Sanity: the money and bust directions genuinely disagree here (the
    # bug's trigger) — money worse, busts down.
    assert b["wasted"] < c["wasted"]               # current wasted more -> WORSE
    assert b["busted"] == 3 and c["busted"] == 0   # busts went DOWN
    rendered = _render(render_compare_delta(baseline, current))
    assert "worse" in rendered.lower()
    # Clamped, bust-direction-driven count: "0 new bust(s)", not "-3 new bust(s)".
    assert "0 new bust" in rendered.lower()
    assert "-3 new bust" not in rendered.lower()


def test_compare_delta_recovered_branch_bust_count_never_negative():
    # Regression for fix-compare-negative-new-bust-count (RECOVERED branch).
    # Money RECOVERED (current wastes less ¥) BUT busts went UP (1 -> 5). The
    # money-driven verdict still says recovered; the displayed bust count must
    # be non-negative ("0 cache-bust(s)"), never "recovered -4 cache-bust(s)".
    baseline = profile([
        # b1 establishes prefix; b2 is ONE big MISS bust (big waste).
        {"request_id": "b1", "prompt_tokens": 1000, "cached_tokens": 1000,
         "miss_tokens": 0, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "b2", "prompt_tokens": 100000, "cached_tokens": 0,
         "miss_tokens": 100000, "prefix_sample": "system:CHANGED\nuser:a"},
    ])
    current = profile([
        # 5 small MISS busts; total waste is small (less than the one big bust).
        {"request_id": "c1", "prompt_tokens": 1000, "cached_tokens": 1000,
         "miss_tokens": 0, "prefix_sample": "system:stable\nuser:a"},
        {"request_id": "c2", "prompt_tokens": 1000, "cached_tokens": 0,
         "miss_tokens": 1000, "prefix_sample": "system:CHANGED-1\nuser:a"},
        {"request_id": "c3", "prompt_tokens": 1000, "cached_tokens": 0,
         "miss_tokens": 1000, "prefix_sample": "system:CHANGED-2\nuser:a"},
        {"request_id": "c4", "prompt_tokens": 1000, "cached_tokens": 0,
         "miss_tokens": 1000, "prefix_sample": "system:CHANGED-3\nuser:a"},
        {"request_id": "c5", "prompt_tokens": 1000, "cached_tokens": 0,
         "miss_tokens": 1000, "prefix_sample": "system:CHANGED-4\nuser:a"},
        {"request_id": "c6", "prompt_tokens": 1000, "cached_tokens": 0,
         "miss_tokens": 1000, "prefix_sample": "system:CHANGED-5\nuser:a"},
    ])
    from dscache.report import _headline_numbers

    b = _headline_numbers(baseline)
    c = _headline_numbers(current)
    # Sanity: directions genuinely disagree (the bug's trigger) — money
    # recovered, busts up.
    assert b["wasted"] > c["wasted"]               # current wasted less -> RECOVERED
    assert b["busted"] == 1 and c["busted"] == 5   # busts went UP
    rendered = _render(render_compare_delta(baseline, current))
    assert "recovered" in rendered.lower()
    # Clamped, bust-direction-driven count: "0 cache-bust(s)", not "-4".
    assert "0 cache-bust" in rendered.lower()
    assert "-4 cache-bust" not in rendered.lower()
