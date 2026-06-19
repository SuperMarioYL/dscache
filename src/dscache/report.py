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
    busted = sum(1 for e in entries if e.busted_against is not None)
    total_actual = sum((e.cost_actual for e in entries), Decimal("0"))
    total_ideal = sum((e.cost_ideal for e in entries), Decimal("0"))
    wasted = total_actual - total_ideal

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
