[简体中文](./README.md) · [Website](https://dscache.lei6393.com) · [GitHub](https://github.com/SuperMarioYL/dscache)

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/hero-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/hero-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/hero-dark.svg">
  <img src="./assets/presentation/hero-light.svg" width="960" alt="Hero diagram">
</picture>

# dscache

**See cache-hit and cache-miss usage per request.**

dscache wraps a compatible client to record reported prompt-cache usage, then profiles the saved ledger into HIT, PARTIAL, MISS or UNKNOWN tiers.

v0.9.0 corrects reports and suggestions for all-UNKNOWN ledgers and ledgers without prefix-bust records, avoiding definite cache-loss claims when the evidence is absent.

## Why use it

A total prompt count can hide changes in the cached-input share. Keeping the split per request helps investigate a regression without assuming every miss was caused by a prompt edit.

- **Keep usage splits** — Cached and missed prompt tokens are separate fields.
- **Retain unknown states** — Missing fields do not become a fabricated cache hit.
- **Suggest without rewriting** — Reorder analysis leaves the request unchanged.

## Architecture

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/architecture-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/architecture-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/architecture-dark.svg">
  <img src="./assets/presentation/architecture-light.svg" width="960" alt="Architecture diagram">
</picture>

The wrapper records usage fields and prefix metadata locally. profile derives tiers and prefix fingerprints, then relates changed-prefix misses to a prior reference. report renders the ledger; reorder offers suggestions without rewriting requests.

| Component | Responsibility |
| --- | --- |
| `Compatible client` | src/dscache/wrapper.py |
| `Local ledger` | JSONL usage records |
| `Cache profiler` | src/dscache/profiler.py |
| `Report / suggestions` | report.py; reorder.py |

## Install and quickstart

Build with the version declared in the repository manifest. Run the example from the repository root.

```bash
git clone https://github.com/SuperMarioYL/dscache.git
cd dscache
uv venv .venv
uv pip install --python .venv/bin/python -e .
source .venv/bin/activate
```

Profile three explicit rows: a high-hit request, an identical-prefix miss, and a request without cache-split data.

```bash
.venv/bin/python examples/presentation-demo.py
```

## Recorded demo

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/process-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/process-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/process-dark.svg">
  <img src="./assets/presentation/process-light.svg" width="960" alt="Process diagram">
</picture>

The three rows classify as HIT, MISS and UNKNOWN; the identical-prefix miss is not linked to a prefix mutation.

```text
{"request": "one", "tier": "HIT", "cached": 95, "miss": 5, "busted_against": null}
{"request": "two", "tier": "MISS", "cached": 5, "miss": 95, "busted_against": "one"}
{"request": "three", "tier": "UNKNOWN", "cached": null, "miss": null, "busted_against": null}
```

The complete command and output are recorded in [docs/demo-results.json](./docs/demo-results.json). Inputs and reproduction code are included in the repository.

![Existing terminal recording](./assets/demo.gif)

The existing recording is retained for context; the text example above documents the reproducible scenario.

## Usage

The CLI exposes the following operations. Commands after the example use your own paths or identifiers.

```bash
# Fake-client ledger example, no API key:
python examples/quickstart.py
dscache report
dscache suggest
dscache report --ledger .dscache/ledger.jsonl
```

## Configuration

wrap(client) delegates actual model calls to your existing client and writes the local ledger. --ledger/-l selects the report input; the default is .dscache/ledger.jsonl. Report thresholds classify at least 90% cached as HIT and at most 10% as MISS.

## Integrations and responsibilities

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/integrations-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/integrations-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/integrations-dark.svg">
  <img src="./assets/presentation/integrations-light.svg" width="960" alt="Integrations diagram">
</picture>

The following routes are implemented in the source. Choose the input that matches your task and keep the resulting artifact with your project.

| Route | Implemented role |
| --- | --- |
| Client response usage | Cached and missed prompt tokens |
| JSONL ledger | Local persisted records |
| Prefix fingerprint | Limited leading text sample |
| Reports / suggestions | Read-only analysis |

## Limits and next steps

- An identical prefix can miss for server-side reasons. The profiler does not treat every cache miss as proof of a client mutation.
- Price calculations use repository rate constants and an all-cached counterfactual. They are estimates, not a current provider bill or guaranteed recoverable savings.
- UNKNOWN indicates missing cache-split fields. Prefix fingerprinting covers a limited leading sample and is not full-request equivalence.

Provider usage compatibility and richer prefix attribution need representative traces. Hosted team dashboards are separate future work.

## License and contributions

See [LICENSE](./LICENSE). When reporting an issue, include a minimal input, the command, and the observed output.
