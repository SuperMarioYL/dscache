"""Terminal reports rendered with ``rich``.

:func:`render_report` (m1) prints the per-request HIT / PARTIAL / MISS table
with cached vs miss token counts and per-request actual cost at DeepSeek
two-tier pricing.

:func:`render_headline` (m3 — minimal here, the shareable one-liner) sums
``cost_actual - cost_ideal`` into the "busted N×, cost X.Yx ideal, ¥Z wasted"
sentence. The full m3 money report is a follow-on milestone.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .profiler import CacheLedgerEntry, Tier

_TIER_STYLE = {
    Tier.HIT: "bold green",
    Tier.PARTIAL: "bold yellow",
    Tier.MISS: "bold red",
    Tier.UNKNOWN: "dim",
}


def _money(value: Decimal) -> str:
    return f"¥{value:.4f}"


def render_report(entries: Sequence[CacheLedgerEntry], console: Console | None = None) -> None:
    """Print the per-request cache-tier ledger table + the money headline."""
    console = console or Console()

    if not entries:
        console.print(
            Panel(
                Text(
                    "No ledger entries found.\n"
                    "Wrap your client with dscache.wrap(client) and run your "
                    "agent loop first, then re-run `dscache report`.",
                    justify="left",
                ),
                title="dscache",
                border_style="cyan",
            )
        )
        return

    table = Table(title="dscache — prefix-cache profit & loss", title_style="bold cyan")
    table.add_column("#", justify="right", style="dim")
    table.add_column("request", overflow="fold")
    table.add_column("tier", justify="center")
    table.add_column("prompt", justify="right")
    table.add_column("cached", justify="right", style="green")
    table.add_column("miss", justify="right", style="red")
    table.add_column("cost", justify="right")
    table.add_column("wasted", justify="right")

    for i, e in enumerate(entries, start=1):
        tier_text = Text(e.tier.value, style=_TIER_STYLE.get(e.tier, ""))
        cached = "—" if e.cached_tokens is None else str(e.cached_tokens)
        miss = "—" if e.miss_tokens is None else str(e.miss_tokens)
        wasted_str = _money(e.wasted) if e.wasted > 0 else "—"
        table.add_row(
            str(i),
            e.request_id,
            tier_text,
            str(e.prompt_tokens),
            cached,
            miss,
            _money(e.cost_actual),
            wasted_str,
        )

    console.print(table)
    console.print(render_headline(entries))


def render_headline(entries: Sequence[CacheLedgerEntry]) -> Panel:
    """Build the shareable money headline (m3, minimal).

    *"This run busted the cache N× and cost X.Yx what it should — ¥Z wasted."*
    """
    nums = _headline_numbers(entries)
    busted = nums["busted"]
    total_actual = nums["total_actual"]
    total_ideal = nums["total_ideal"]
    wasted = nums["wasted"]

    if total_ideal > 0:
        ratio = total_actual / total_ideal
        ratio_str = f"{ratio:.2f}×"
    else:
        ratio_str = "n/a"

    if wasted > 0:
        body = Text.assemble(
            ("This run busted the cache ", ""),
            (f"{busted}×", "bold red"),
            (" and cost ", ""),
            (ratio_str, "bold red"),
            (" what it should — ", ""),
            (f"{_money(wasted)} wasted", "bold red"),
            (".", ""),
        )
        border = "red"
    else:
        body = Text.assemble(
            ("Cache held stable — ", ""),
            ("¥0 wasted", "bold green"),
            (". Your prefix discount is intact.", ""),
        )
        border = "green"

    return Panel(body, title="headline", border_style=border)


def _headline_numbers(entries: Sequence[CacheLedgerEntry]) -> dict[str, Decimal]:
    """Sum the money/bust numbers used by both the headline and the compare delta.

    UNKNOWN-tier entries (DeepSeek omitted the cache split) are excluded from
    the sums — we cannot judge their hit/miss, so they must not fabricate
    phantom wasted ¥ (fix fix-unknown-tier-fabricates-wasted-money).
    """
    judged = [e for e in entries if e.tier is not Tier.UNKNOWN]
    busted = sum(Decimal(1) for e in entries if e.busted_against is not None)
    total_actual = sum((e.cost_actual for e in judged), Decimal("0"))
    total_ideal = sum((e.cost_ideal for e in judged), Decimal("0"))
    wasted = total_actual - total_ideal
    return {
        "busted": busted,
        "total_actual": total_actual,
        "total_ideal": total_ideal,
        "wasted": wasted,
    }


def render_compare_delta(
    baseline: Sequence[CacheLedgerEntry],
    current: Sequence[CacheLedgerEntry],
    *,
    baseline_label: str = "baseline",
    current_label: str = "current",
) -> Panel:
    """Print the before/after cache-savings delta between two profiled runs.

    The shareable artifact for the plan's Section 7 GTM before/after-bill
    writeup (feat feat-report-compare-baseline). Stays in the profiler's OWN
    accounting path: it sums the same numbers :func:`render_headline` already
    computes, across two ledgers, and prints ONE rich Panel — no server, no
    persistence, no team aggregation.

    Honesty-preserving: the panel says "recovered", NOT "saved" — dscache cannot
    prove the user pinned the prefix (they may have changed the prompt, the
    model, or the run); it reports only that the judged requests in the current
    ledger cost less wasted ¥ than the judged requests in the baseline ledger.
    """
    b = _headline_numbers(baseline)
    c = _headline_numbers(current)

    recovered_wasted = b["wasted"] - c["wasted"]
    recovered_busts = b["busted"] - c["busted"]

    def _ratio(nums: dict[str, Decimal]) -> str:
        if nums["total_ideal"] > 0:
            return f"{(nums['total_actual'] / nums['total_ideal']):.2f}×"
        return "n/a"

    baseline_ratio = _ratio(b)
    current_ratio = _ratio(c)

    if recovered_wasted > 0:
        body = Text.assemble(
            ("Applying the suggestion recovered ", ""),
            (f"{recovered_busts}", "bold green"),
            (" cache-bust(s) and ", ""),
            (f"{_money(recovered_wasted)}", "bold green"),
            (" of wasted spend — cost ratio dropped from ", ""),
            (baseline_ratio, "bold red"),
            (" to ", ""),
            (current_ratio, "bold green"),
            (".", ""),
        )
        border = "green"
    elif recovered_wasted < 0:
        body = Text.assemble(
            ("Cache got WORSE — ", ""),
            (f"{-recovered_busts}", "bold red"),
            (" new bust(s) and ", ""),
            (f"{_money(-recovered_wasted)}", "bold red"),
            (" more wasted (ratio ", ""),
            (baseline_ratio, "bold green"),
            (" -> ", ""),
            (current_ratio, "bold red"),
            ("). Re-check your prefix pin.", ""),
        )
        border = "red"
    else:
        body = Text.assemble(
            ("No change in wasted spend (", ""),
            (baseline_ratio, "dim"),
            (" -> ", "dim"),
            (current_ratio, "dim"),
            ("). Prefix discount unchanged.", ""),
        )
        border = "yellow"

    caveat = Text(
        f"\nRecovered reflects only the requests profiled in {current_label} vs "
        f"{baseline_label}; dscache cannot prove you pinned the prefix (you may "
        f"have changed the prompt or run), so this says 'recovered', not 'saved'.",
        style="dim",
    )
    full = Text.assemble(body, "\n", caveat)

    return Panel(
        full,
        title=f"compare — {baseline_label} → {current_label}",
        border_style=border,
    )
