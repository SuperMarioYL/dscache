<div align="right">

**English** | [简体中文](./README.md)

</div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./assets/hero-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="./assets/hero-light.svg">
    <img src="./assets/hero-light.svg" width="880" alt="dscache — DeepSeek prefix-cache profit & loss" />
  </picture>
</p>

<p align="center"><sub>dscache is the prefix-cache profit-and-loss layer that recovers DeepSeek cache discounts for <b>Coding Agent</b> developers.</sub></p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="license" /></a>
  <img src="https://img.shields.io/badge/release-WIP-orange.svg" alt="release" />
  <a href="https://github.com/SuperMarioYL/dscache/actions/workflows/ci.yml"><img src="https://img.shields.io/badge/CI-ci.yml-brightgreen.svg" alt="ci" /></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white" alt="python" />
  <img src="https://img.shields.io/badge/DeepSeek-cache--tier-7c3aed.svg" alt="deepseek" />
  <img src="https://img.shields.io/badge/Coding%20Agent-ready-14b8a6.svg" alt="coding-agent" />
</p>

> **Your DeepSeek agent quietly overpays on every loop — one reshuffled prefix and the whole context-cache discount drops from the cached-input price back to full price, and nothing in your tooling tells you. dscache turns that into a visible, priced, fixable profit-and-loss sheet in two lines of code.**

<h2><img src="https://api.iconify.design/tabler:topology-star-3.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Architecture</h2>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./assets/atlas-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="./assets/atlas-light.svg">
    <img src="./assets/atlas-light.svg" width="880" alt="Your agent code calls a transparent wrapper that reads DeepSeek cache usage and appends to a local ledger; the profiler classifies each request HIT/PARTIAL/MISS, fingerprints the prefix and prices it at two tiers, then feeds the report (P&L + headline) and the reorder suggester (worst bust)">
  </picture>
</p>

A single Python package, one process — no daemon, no server, no network calls of our own. Data flow: your code → `wrapper` (pure pass-through, reads `prompt_cache_hit/miss_tokens`) → `.dscache/ledger.jsonl` → `profiler` (tier + prefix fingerprint + two-tier pricing) → (`report` prints the P&L | `reorder` prints a fix) → terminal.

## Table of Contents

- [Why this exists](#why-this-exists)
- [Install & Quickstart](#install--quickstart)
- [Usage](#usage)
- [Demo](#demo)
- [vs DeepSeek-Reasonix](#vs-deepseek-reasonix)
- [Configuration](#configuration)
- [Pricing / Team plan](#pricing--team-plan)
- [Roadmap](#roadmap)
- [License & Contributing](#license--contributing)

## Why this exists

Generic LLM cost dashboards (Helicone / Langfuse) count tokens at OpenAI pricing semantics and **have no model of DeepSeek's two-tier (cache-hit vs cache-miss) context-cache pricing**, so they cannot tell whether a request landed in the cheaper cached-input tier, and they cannot detect the *prefix-bust event* — the moment a prefix change silently invalidated the cache. That cost lives inside agent loops: the same long prefix repeats hundreds of times, and a single injected timestamp or reordered tool list drops you from the discount tier back to full price. dscache reads DeepSeek's `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` and turns an invisible, recurring overspend into a measured, controllable line item.

## Install & Quickstart

Three commands from a cold clone to your first P&L sheet:

```bash
pip install dscache              # < 20s
dscache demo                     # write a sample ledger (no API key needed) and print the P&L
dscache suggest                  # see the worst bust + a reorder suggestion
```

To instrument your own code, change two lines:

```python
import dscache
from openai import OpenAI

client = dscache.wrap(OpenAI(base_url="https://api.deepseek.com", api_key="sk-..."))
# run your agent loop as usual — dscache transparently records each response's
# cache usage to .dscache/ledger.jsonl
```

Then run `dscache report` in your terminal.

<details>
<summary>sample output</summary>

```
                    dscache — prefix-cache profit & loss
┏━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓
┃ # ┃ request           ┃ tier ┃ prompt ┃ cached ┃ miss ┃    cost ┃  wasted ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩
│ 1 │ chatcmpl-demo-000 │ HIT  │   4200 │   4120 │   80 │ ¥0.0022 │       — │
│ 4 │ chatcmpl-demo-003 │ MISS │   4200 │    120 │ 4080 │ ¥0.0082 │ ¥0.0061 │
└───┴───────────────────┴──────┴────────┴────────┴──────┴─────────┴─────────┘
╭────────────────────────────────── headline ──────────────────────────────────╮
│ This run busted the cache 1× and cost 1.53× what it should — ¥0.0067 wasted. │
╰──────────────────────────────────────────────────────────────────────────────╯
```

</details>

<h2><img src="https://api.iconify.design/tabler:terminal-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Usage</h2>

Three commands, three workflows. Full script in [`examples/`](./examples/quickstart.py).

```bash
# 1) see which tier each request landed in, and how much this run wasted
dscache report

# 2) get a prefix-reorder suggestion for the worst bust (a suggestion — it
#    never mutates your request in-flight)
dscache suggest

# 3) point at a specific ledger (default .dscache/ledger.jsonl)
dscache report --ledger ./traces/run-42.jsonl
```

Library API (the two-line integration):

```python
client = dscache.wrap(your_deepseek_client)          # transparent proxy, returns the response unchanged
entries = dscache.profile(dscache.load_ledger(path)) # or get structured ledger entries directly
```

<h2><img src="https://api.iconify.design/tabler:photo.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Demo</h2>

The full script lives in [`docs/demo.tape`](./docs/demo.tape) (vhs script, rendered to `assets/demo.gif` on tag by CI).

![demo](assets/demo.gif)

> The GIF is rendered and committed by `.github/workflows/demo.yml` on the first `v*` tag.

## vs DeepSeek-Reasonix

[esengine/DeepSeek-Reasonix](https://github.com/esengine/DeepSeek-Reasonix) (23k★) baked prefix-cache stability into one concrete coding agent — which is itself proof the pain is real. But it **hard-codes the stability logic inside a product**; it is not a reusable measurement/optimizer primitive you can attach to *your own* pipeline. Honestly, Reasonix is the more complete experience at "just leave it running"; dscache fills the other slot — reusable, embeddable, and showing you every single bust.

| Capability | dscache | DeepSeek-Reasonix |
| --- | :---: | :---: |
| Per-request cache hit/bust measurement | ✓ | — |
| Two-tier (hit/miss) pricing + wasted ¥ | ✓ | — |
| Attaches to any DeepSeek client (two-line wrap) | ✓ | — |
| Full out-of-the-box coding-agent experience | — | ✓ |
| Prefix stability on by default | suggest-only, never mutates | ✓ (baked into the product) |

## Configuration

v0.1 needs **no config file** and no keys beyond your existing DeepSeek key. Tunables are CLI flags:

| Option | Type | Default | Meaning |
| --- | --- | --- | --- |
| `--ledger` / `-l` | path | `.dscache/ledger.jsonl` | Path to the ledger (JSONL) file |
| `--requests` / `-n` | int | `8` | How many sample requests `dscache demo` writes |

## Pricing / Team plan

The v0.1 OSS library is **free forever**, and **no v0.1 feature is paywalled**.

For small teams (3–10 devs) running shared DeepSeek-backed coding agents and already feeling the ¥ bill, there's a **hosted team plan**: devs upload their local `ledger.jsonl` traces; the service aggregates cache-discount savings across the team's agents over time, charts the trend, and **alerts on regressions** (e.g. "the team's HIT rate dropped 18% this week — a prompt-template change busted the cache"). It is the same local report, served + persisted + monitored.

- **Price:** **¥39 / seat / month** (~$5.50), 3-seat team minimum → ~¥117/mo entry; annual gets 2 months free.
- **Shortest "here's my card" path:** `dscache report --upload` → prints a team-dashboard share URL → 14-day free trial → after the trial, the regression-alert email links to a 2-click Stripe / Alipay checkout. No sales call.

The price sits below the ¥-saved the report demonstrates, so it justifies itself.

## Roadmap

- [x] **m1 · wrap & profile** — `dscache.wrap()` transparently records the ledger; `dscache report` prints the per-request HIT/PARTIAL/MISS table + two-tier pricing.
- [ ] **m2 · reorder suggest** — `profiler` computes prefix fingerprints and flags bust events; `dscache suggest` prints a concrete reorder that restores the stable cached span.
- [ ] **m3 · money report** — sum `cost_actual − cost_ideal` into one shareable line: "busted N×, cost X.Yx ideal, ¥Z wasted".
- [ ] Hosted team plan (upload aggregation + regression alerts, above).
- [ ] Cross-model support (Kimi / Qwen / GLM, post-v0.1).

## License & Contributing

[MIT](./LICENSE) licensed. File an issue with a real wasted-money number from one of your runs, or open a PR — especially for new two-tier pricing calibrations and reorder strategies.

## Share this

```
dscache — the prefix-cache P&L for your DeepSeek Coding Agent. Two lines to see
every request HIT or MISS the discount, plus a copy-paste reorder fix to win it
back. https://github.com/SuperMarioYL/dscache
```

> After pushing, set repo topics: `gh repo edit --add-topic deepseek --add-topic agent --add-topic prefix-cache`

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
