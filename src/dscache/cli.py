"""``dscache`` command-line interface (typer).

Commands
--------
- ``dscache report``   — print the HIT/PARTIAL/MISS table + money headline (m1).
- ``dscache suggest``  — print the prefix-reorder suggestion for the worst bust (m2).
- ``dscache demo``     — write a sample ledger (no API key needed) so you can see
                         the report end-to-end in seconds.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import __version__
from .profiler import load_ledger, profile
from .reorder import suggest_reorder
from .report import render_report
from .wrapper import DEFAULT_LEDGER_PATH, append_record

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="A prefix-cache profit-and-loss layer for DeepSeek coding agents.",
)
console = Console()


@app.callback()
def main() -> None:
    """dscache — see when your DeepSeek agent busts the prefix-cache discount."""


@app.command()
def version() -> None:
    """Print the dscache version and exit."""
    console.print(f"dscache {__version__}")


@app.command()
def report(
    ledger: Path = typer.Option(
        DEFAULT_LEDGER_PATH, "--ledger", "-l", help="Path to the ledger JSONL file."
    ),
) -> None:
    """Print the per-request cache-tier table and the wasted-money headline."""
    entries = profile(load_ledger(ledger))
    render_report(entries, console)


@app.command()
def suggest(
    ledger: Path = typer.Option(
        DEFAULT_LEDGER_PATH, "--ledger", "-l", help="Path to the ledger JSONL file."
    ),
) -> None:
    """Suggest a prefix reorder for the worst cache-bust (m2)."""
    entries = profile(load_ledger(ledger))
    suggestion = suggest_reorder(entries)
    if suggestion is None:
        console.print("[green]No cache-bust detected — your prefix is stable.[/green]")
        raise typer.Exit()
    console.print(f"[bold red]Worst bust:[/bold red] {suggestion.request_id}")
    console.print(f"[dim]wasted ¥{suggestion.wasted:.4f}[/dim]")
    if suggestion.attribution is not None and suggestion.attribution.segment is not None:
        console.print(
            f"[bold yellow]First diverging segment:[/bold yellow] "
            f"{suggestion.attribution.segment}"
        )
    console.print(suggestion.message)


@app.command()
def demo(
    ledger: Path = typer.Option(
        DEFAULT_LEDGER_PATH, "--ledger", "-l", help="Where to write the sample ledger."
    ),
    requests: int = typer.Option(8, "--requests", "-n", help="How many sample requests to write."),
) -> None:
    """Write a sample ledger (no DeepSeek key needed) and print the report.

    Simulates a coding-agent loop that reuses a big stable prefix, then busts it
    once (a reordered tool list) so the report has something to show.
    """
    if ledger.exists():
        ledger.unlink()

    stable_prefix = "system:You are a DeepSeek coding agent.\nuser:Refactor module"
    busted_prefix = "system:You are a DeepSeek coding agent. [t=1718] \nuser:Refactor module"

    for i in range(requests):
        # Bust the cache on the middle request to demonstrate a MISS.
        busted = i == requests // 2
        prompt_tokens = 4200
        if busted:
            cached, miss = 120, prompt_tokens - 120  # almost entirely a miss
            prefix = busted_prefix
        else:
            cached, miss = prompt_tokens - 80, 80  # almost entirely cached
            prefix = stable_prefix
        record = {
            "request_id": f"chatcmpl-demo-{i:03d}",
            "timestamp": time.time(),
            "model": "deepseek-chat",
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached,
            "miss_tokens": miss,
            "prefix_sample": prefix,
        }
        append_record(ledger, record)

    console.print(f"[cyan]Wrote {requests} sample requests to {ledger}[/cyan]\n")
    entries = profile(load_ledger(ledger))
    render_report(entries, console)


if __name__ == "__main__":  # pragma: no cover
    app()
