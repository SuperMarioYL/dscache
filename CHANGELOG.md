# Changelog

## v0.8.0

A continuation of the honesty/correctness-deepening arc (amend-dscache-v0.8.0).
Three `type:fix` milestones close contradictions and gaps the prior honesty
fixes themselves surfaced or the v0.7.0 changelog flagged — all in the
report/suggestion path, no new primitive, no server, no scope drift.

### Fixes

- **The money headline no longer prints a self-contradictory "busted the cache
  0×" next to wasted spend.** After the v0.6.0/v0.7.0 cold-start fixes, a
  genuine MISS with no prior stable prefix correctly leaves `busted_against`
  unset, so the bust count is 0 while wasted ¥ is positive. The old headline
  had only a `wasted > 0` branch that unconditionally opened with "busted the
  cache {busted}×", so it read "busted the cache 0× ... ¥Z wasted" — a bust
  count of zero next to a non-zero wasted figure. The two concepts are
  different: "busted N×" means a CLIENT-side prefix divergence against a prior
  stable prefix; "wasted ¥" means miss tokens cost money regardless. A new
  third branch reports the waste honestly across the miss requests without the
  phantom bust count (cold start; re-run after a cache hit to attribute busts).
  The two existing branches (real busts; cache held stable) are unchanged.

- **`dscache report --compare` no longer fabricates a "recovered" panel when
  one side has no judged cache requests.** `render_compare_delta` drove its
  verdict off `recovered_wasted = baseline_wasted - current_wasted` with no
  guard for an empty side. An empty or all-UNKNOWN current ledger
  (`current_wasted == 0`) made `recovered_wasted > 0` for any baseline that had
  waste, printing a fake "recovered N bust(s) and ¥Z" panel directly above the
  report table's "No ledger entries found" line for the same ledger (the mirror
  case fabricated a "WORSE" panel against an empty baseline). The fix guards:
  when either side has no judged requests, it emits an honest "no judged cache
  requests" hint instead of a verdict — a before/after delta requires judged
  requests on both sides.

- **`suggest_reorder`'s actionable "Pin X" line names the actual diverging
  segment the attribution already computed.** The suggestion hard-coded "Pin
  the system prompt and tool list" regardless of where `attribute_bust` located
  the divergence, so a bust in a USER message (attribution segment
  `user (segment[2])`) was met with "Pin the system prompt and tool list" —
  fixing the wrong segment. The v0.7.0 changelog flagged this as an open
  question but did not implement it. The "Pin X" clause now references the
  attribution's segment when one was found (`Pin user (segment[2]) to the exact
  byte order used in r1` / `Pin tools[1]...`), falling back to the generic line
  only when no client-side divergence was located (a clean diff / server-side
  eviction). Detect-only; never mutates the request.

## v0.7.0

A continuation of the honesty/correctness-deepening arc. One `type:fix`
milestone folded from a bug-hunter `confidence:high` finding closes the
genuinely-new-prefix sub-case the v0.6.0 `fix-identical-prefix-miss-false-bust`
left open.

### Fixes

- **A genuinely-new-prefix MISS no longer busts against a prior MISS when no
  stable prefix exists.** The v0.6.0 `fix-identical-prefix-miss-false-bust`
  suppressed the REPEAT-same-fingerprint MISS sub-case (a prior MISS whose exact
  prefix was sent again) but left the GENUINELY-NEW-prefix sub-case open: when no
  prior HIT existed at all (cold start — the first calls of a fresh agent
  session), a later MISS with a DIFFERENT fingerprint was "genuinely new", so it
  fell back to `bust_reference = last_request_id`, which (with no HIT) was the
  previous MISS. The previous MISS never cached (it is not a `seen_prefixes`
  owner), so the new-prefix MISS busted against a reference that was never stable
  — exactly the phantom "busted N×" inflation the v0.6.0 rationale targeted for
  the repeat sub-case. The v0.6.0 comment even stated the fallback should be the
  "last stable prefix" but still advanced `last_request_id` for a MISS, so the
  code contradicted its own stated intent. Reproduced: two different-prefix
  MISSes with no prior HIT yielded `busted=1` and a `suggest_reorder` message
  telling the user to "pin to the byte order used in r1" — pinning to a
  never-cached prefix cannot recover the discount, contradicting the honesty
  thesis every prior fix deepened. The profiler now advances `last_request_id`
  (the fallback) only for requests that actually cached (`HIT` or `PARTIAL`), so
  a cold-start all-MISS different-prefix run reports `busted=0` (nothing cached,
  nothing to have diverged from) — the honest answer. `last_hit_request_id` (the
  primary reference) and the `seen_prefixes` owner path are unchanged, so every
  prior-HIT bust case stays green. Two regression tests pin the invariant: a
  cold-start all-MISS different-prefix run has every `busted_against` `None` and
  headline `busted == 0`; and a genuinely-new-prefix MISS after a prior PARTIAL
  still busts against it (the fix does not over-suppress legitimate busts).

## v0.6.0

A deepening pass over the honesty/correctness thesis. Two `type:fix`
milestones folded from bug-hunter confidence:high findings close the version-
reporting drift the v0.5.0 fix was supposed to end and stop a repeat same-
fingerprint MISS from inflating the central "busted N×" headline; one
`type:feature` milestone folds cacheguard's byte-level prefix-mutation linter
into dscache's OWN attribute path as detection-only deepening, retiring the
orphan sibling.

### Fixes

- **`__version__` now tracks the packaged version via
  `importlib.metadata`, and `pyproject` / `VERSION` / `CHANGELOG` bump with
  the release tag.** The v0.5.0 fix `fix-version-string-stale-0-3-0` was
  chartered to make `dscache.__version__` track the packaged version
  ("derive it at runtime via `importlib.metadata.version('dscache')` ... so
  the runtime string tracks the packaged version and cannot drift again"),
  but the shipped code only hardcoded `__version__ = "0.5.0"` (no
  `importlib.metadata` derivation) AND never bumped the other sources of
  truth: `pyproject.toml` was still `version = "0.4.0"`, the `VERSION` file
  was still `0.4.0`, and `CHANGELOG.md` had no `## v0.5.0` section. The
  release workflow (`.github/workflows/release.yml` runs `python -m build`,
  which reads `pyproject.toml`) therefore built a wheel named
  `dscache-0.4.0` for the git-tagged v0.5.0 release — `pip show dscache`
  reported 0.4.0 while `dscache version` printed "dscache 0.5.0", and
  `pip install dscache==0.5.0` could not resolve. The regression test only
  asserted `__version__ == "0.5.0"`, so it passed while the package metadata
  was 0.4.0 — it did not guard the drift it was written to prevent.
  `pyproject.toml`, the `VERSION` file, and the missing `## v0.5.0`
  CHANGELOG section now all read 0.6.0; `__init__.py` derives `__version__`
  at runtime via `importlib.metadata.version("dscache")` inside a
  try/except (`PackageNotFoundError` → literal fallback), so bumping
  `pyproject.toml` alone updates the runtime string. A new test asserts
  `__version__ == importlib.metadata.version("dscache")` (when installed)
  and that `pyproject` / `VERSION` / `__version__` all agree.

- **A repeat same-fingerprint MISS is no longer counted as a client-side
  bust.** When a run has no prior HIT, `bust_reference = last_hit_request_id
  or last_request_id` falls back to `last_request_id`, which the v0.3.0 fix
  only excluded UNKNOWN-tier entries from advancing — so the fallback could
  still land on a prior MISS. A MISS never registers as a fingerprint owner
  (v0.3.0's `fix-bust-reference-quality`), so a LATER request with the SAME
  sampled prefix was treated as a NEW fingerprint and, because its tier was
  MISS/PARTIAL, `busted_against` was set to the prior MISS even though the
  two requests' prefix samples were byte-IDENTICAL. Reproduced: two
  identical-prefix MISSes with no prior HIT yielded `busted=1` and a
  self-contradicting `suggest_reorder` ("diverged from request r1") while
  its own `attribute_bust` reported "PREFIX STABLE ... server-side
  eviction". The profiler now tracks every previously-seen fingerprint
  regardless of tier (`seen_any_prefix`) and, in the new-prefix branch, does
  NOT set `busted_against` when the fingerprint is already in
  `seen_any_prefix` — a repeat prefix that still MISS/PARTIAL'd is a
  server-side eviction (the client prefix did not diverge), which the
  honesty caveat says dscache must not count as a client-side bust. It only
  falls back to `bust_reference` when the fingerprint is genuinely new. A
  regression test asserts the second identical-prefix MISS has
  `busted_against is None` and the headline `busted` count is 0.

### Features

- **Byte-level prefix-divergence attribution.** `attribute.py` now diffs
  two serialized request heads at byte granularity (not just segment-level),
  naming the exact diverging byte span when a bust is detected — e.g.
  `PREFIX BUST: tools[3] byte offset 412 reordered vs req r17`. This folds
  cacheguard's byte-level prefix-mutation linter into dscache's OWN
  attribute path as DETECTION-only deepening, retiring the orphan cacheguard
  sibling (0 stars) by absorbing its detection value into the product it
  duplicated — exactly the "DEEPEN the honesty/correctness thesis, not fork
  into a sibling re-implementation" posture the v0.5.0 banned-paradigm
  entry prescribes. Strictly detect-and-attribute: it NEVER mutates the
  request. The cacheguard prefix-MUTATION capability (rewriting the prefix
  to stabilize cache) is explicitly DROPPED, consistent with dscache's
  "suggest only, never mutate" thesis and the out-of-scope standalone-linter
  ban. The honesty caveat is unchanged: a client can reason only about its
  OWN prefix divergence; it cannot observe or control DeepSeek's server-side
  global LRU eviction, so byte-level attribution explains a client-caused
  bust at finer granularity, not a server-side eviction.

## v0.5.0

A bug-fix + anti-self-clone iteration, from amendment
`amend-dscache-v0.5.0`. Two `type:fix` milestones folded from bug-hunter
confidence:high findings; the standalone DeepSeek prefix-cache-stabilizer
CLI/library paradigm is codified as portfolio-banned to stop self-cloning.

### Fixes

- **The `dscache report --compare` delta panel no longer prints a negative
  bust count.** `render_compare_delta` drove its displayed bust-count delta
  off the money sign (`recovered_wasted = b[wasted] − c[wasted]`) while
  printing the bust delta (`b[busted] − c[busted]`) whose sign is
  independent, so the bust number went negative and contradicted the verdict
  exactly when the user needs the before/after read. Reproduced both
  branches: a bust-heavy baseline vs an all-HIT-with-uncached-miss current
  hit the WORSE branch and printed "−3 new bust(s) and ¥2.9954 more wasted";
  the mirror case hit the RECOVERED branch and printed "recovered −5
  cache-bust(s)". The fix drives the displayed bust count from the BUST
  sign, clamped non-negative (`max(c[busted] − b[busted], 0)` in WORSE;
  `max(b[busted] − c[busted], 0)` in RECOVERED), alongside the money-driven
  verdict so the two never contradict (at `src/dscache/report.py`).

- **`__version__` bumped to track the shipped 0.4.0.** `__version__` was
  never bumped during the v0.4.0 iteration, so `dscache version` printed
  "0.3.0" for a 0.4.0 install (lagging `pyproject.toml` / `VERSION` /
  `CHANGELOG.md` / the build metadata, all 0.4.0). This v0.5.0 release set
  `__version__ = "0.5.0"`; the v0.6.0 fix above completes the original
  prescription by deriving it via `importlib.metadata` and keeping
  `pyproject` / `VERSION` / `CHANGELOG` in sync with the release tag (at
  `src/dscache/__init__.py`).

### Other

- **Standalone DeepSeek prefix-cache-stabilizer CLI/library codified as
  portfolio-banned.** Subsequent scans (2026-06-20 / 06-22 / 06-23 / 06-27)
  regenerated near-duplicate winners (t9dcache, dskprfx, dscache1,
  cacheguard) because the dedup gate dedups by `need_id`, not by concept.
  Future dscache iterations must DEEPEN the honesty/correctness thesis, not
  fork into a sibling re-implementation (reaffirms the existing tokensched /
  cachepin / cacheguard sibling-lane bans already in `out_of_scope`).

No stack change; no target files added/removed; no `out_of_scope` additions;
`launch_post_changes: []`; `raw_patches: []`; `prose_patches: []`. No action
on the 5-day external traction signal (premature vs the 30-day kill window;
0 issues / 0 PRs / no user-filed wasted-money issues).

## v0.4.0

A bug-hunt + git-sync pass. Two `type:fix` folded from bug-hunter HIGH
findings close the asymmetry the v0.3.0 ideal fix introduced and restore
segment attribution on real multi-line prompts; the license spec is
reconciled with the shipped Apache 2.0 repo; the post-ship GitHub Pages
product site is codified as a distribution channel.

### Fixes

- **`cost_actual` prices the unaccounted split gap, so a MISS can't show
  negative waste.** v0.3.0's `cost_ideal` fix raised the ideal to the full
  `prompt_tokens * hit`, but left `cost_actual` pricing only `cached + miss` —
  so when the provider's split was inconsistent (`cached + miss <
  prompt_tokens`, the exact case the v0.3.0 docstring says happens "in
  practice") the gap tokens (`prompt − cached − miss`) were free and a cache
  MISS could render *cheaper than ideal*: reproduced `wasted = −0.000045` on a
  tier=MISS (`cached=10, miss=100, prompt=500`), and that negative per-request
  waste then subtracted from the headline's total `¥Z wasted`, understating the
  central number. `price_request` now prices the gap
  (`max(prompt − cached − miss, 0)`) at the miss rate inside `cost_actual`, so
  `cost_actual ≥ cost_ideal` always and a MISS never shows negative waste; the
  consistent-split case (`gap=0`) is unchanged.

- **Multi-line message content no longer shatters segment attribution.**
  `_prefix_sample` joins segments with `"\n"` and `attribute._split_segments`
  recovers them by splitting on `"\n"`, but the message loop embedded content
  *raw* — so any system/user prompt with a literal `"\n"` (the common
  coding-agent case) was shattered into N spurious `segment[K]` labels and
  `attribute_bust` reported a meaningless `stable_through` instead of naming
  the diverging message. Reproduced: `"Rules:\n1. Do X"` vs `"...1. Do Y"`
  yielded `segment="segment[1]"` instead of naming the system message. Message
  content is now serialized via the same `_serialize_value` (`json.dumps`)
  path already used for tools — which escapes `"\n"` — so `"\n"` is an
  unambiguous separator and the diverging segment labels the message, not
  `segment[K]` (tool blocks were already safe via `json.dumps`). This is a
  fingerprint-format bump, accepted as a v0.4.0 ledger-contract change (the
  sampled prefix is per-run and never persisted verbatim).

### Other

- **License spec reconciled with the shipped Apache 2.0 repo.** The v0.3.0
  plan's `readme_spec.footer` still exampled `MIT`; the shipped repo adopted
  Apache 2.0. The footer, badge, and LICENSE/pyproject license field now read
  Apache-2.0 to match.
- **GitHub Pages product site codified as a distribution channel** — a static
  marketing surface that mirrors the before/after-bill headline, explicitly
  *not* the out-of-scope hosted dashboard or SaaS backend. No new feature
  scope.

### Deferred

- **`render_compare_delta` can print a negative "new bust(s)" count** and label
  a bust-reducing run as "Cache got WORSE". The defect is real and reproduced
  but is confidence:medium with no filed issue corroborating it, so it is
  deferred per the proposer charter's confidence gate; re-file it as an issue
  and it becomes a v0.4.1 / v0.5.0 fix.

## v0.3.0

A correctness pass that closes three residual holes in v0.2.0's own
sampling, pricing, and attribution paths — the same honesty thesis, extended
to the cases v0.2.0 left half-fixed — plus one small feature that unblocks the
before/after-bill writeup the README promised.

### Fixes

- **The prefix sample is capped at segment boundaries, not sliced mid-segment.**
  `_prefix_sample` enforced the 2048-char budget only inside the messages
  loop and then did a final `sample[:2048]` slice that could cut a tool block
  in half. For a coding agent whose tool list dominates the budget (the common
  case) the sample ended mid-tool — corrupting segment-level attribution with
  a stub segment — and message text past the tool head was never captured, so
  two requests with identical tools but a diverged system message got the
  *same* fingerprint and a real system-message bust was invisible. The budget
  is now applied incrementally across all segments (tools, `tool_choice`,
  `response_format`, messages); a segment that would overflow the remaining
  budget is never appended, so no segment is ever truncated mid-way.

- **`cost_ideal` is based on the full `prompt_tokens`, not `cached + miss`.**
  The counterfactual `price_request` models is "the entire prompt had stayed
  cached", and the entire prompt is `prompt_tokens`. DeepSeek documents
  `prompt_tokens == cached + miss`, but providers surface inconsistent splits
  in practice; when `cached + miss < prompt_tokens` the old ideal was
  understated and the headline overstated wasted ¥ — fabricating phantom
  money on data the user couldn't reconcile against their bill. The ideal now
  uses `prompt_tokens`; behavior is unchanged when the split is consistent.

- **A bust is never attributed to a MISS or UNKNOWN reference.** A MISS never
  cached, so it shouldn't register as the owner of a "stable" prefix — yet it
  did, so a later request with the same sampled head (also a MISS) was busted
  against an unstable owner and `suggest` told you to pin to a prefix that
  itself didn't cache. Likewise the no-prior-HIT fallback advanced
  `last_request_id` on UNKNOWN-tier entries, so a bust could point at a
  request whose cache split DeepSeek never reported. Only HIT/PARTIAL entries
  now register as fingerprint owners, and `last_request_id` only advances on
  judged (non-UNKNOWN) entries.

### Features

- **`dscache report --compare <baseline.jsonl>`** prints the before/after
  cache-savings delta in one panel. Run your agent loop, apply the prefix-
  reorder suggestion from `dscache suggest`, re-run, then `dscache report
  --compare baseline.jsonl` to see the recovered cache-busts, recovered ¥,
  and the cost-ratio drop — the shareable before/after-bill writeup the
  README's go-to-market called for, now one command. Honesty-preserving: the
  panel says "recovered", not "saved" — dscache can't prove you pinned the
  prefix (you may have changed the prompt or run), so it reports only that the
  judged requests in the current ledger wasted less ¥ than the baseline.

## v0.2.0

An honesty-first pass over the profiler. v0.1.0 could call a cache "stable"
when it wasn't, and could invent wasted money out of data we never actually
had. This release fixes the four ways the report could lie, and adds segment-
level attribution so a bust tells you *which* part of the prompt broke.

### Fixes

- **A real MISS that shares a sampled prefix is no longer reported as stable.**
  The 2048-char prefix sample is only a lower bound on DeepSeek's real cache
  key, not the key itself. If two requests happen to share that sampled head
  but DeepSeek still reports a MISS/PARTIAL, that's a genuine bust — we now flag
  it against the prefix's owner instead of silently passing over it. Previously
  this undercounted busts and made `suggest` return nothing on a real failure.

- **UNKNOWN-tier requests no longer fabricate wasted money.** When DeepSeek
  omits the cache-split fields we can't judge hit vs miss, yet the priced
  fallback still produced a miss-vs-hit gap. Summed into the headline, a run
  with zero detected busts could print a large "¥Z wasted" and a 4.00× ratio on
  data we admit we can't judge. UNKNOWN entries now contribute zero waste, and
  the headline excludes them from the actual/ideal totals.

- **Busts are attributed to the most-recent HIT, not the immediate neighbor.**
  We previously pinned a bust to whatever request came right before it, which
  might itself be an unstable prefix — so `suggest` could tell you to match a
  bad reference. We now track the last request that actually HIT and attribute
  against that, falling back to the immediate neighbor only when no stable prior
  prefix exists.

- **The prefix sample now includes tools.** `_prefix_sample` only serialized
  message role+content and ignored `tools` / `tool_choice` / `response_format`.
  For coding agents the cache key is dominated by a large, frequently-reordered
  tool list, so a reordered-tools bust — the exact failure mode the README
  advertises — was invisible. Tools are now serialized ahead of the message
  text (still capped at 2048 chars), so a shuffled tool array changes the
  fingerprint.

### Features

- **Segment-level bust attribution** (`dscache/attribute.py`). When a bust is
  detected against its most-recent-HIT reference, we diff the two serialized
  request heads at segment granularity and name the first diverging segment —
  e.g. `PREFIX BUST: tools[3] diverged vs req r17; segments[0..2] still stable`.
  Surfaced through `dscache suggest` and the reorder suggestion. Detect-and-
  attribute only: it never mutates the request. The output carries an explicit
  honesty caveat — a client can reason only about its own prefix divergence and
  cannot observe or control DeepSeek's server-side global LRU eviction, so a
  clean client-side diff means "you didn't cause this bust", not "this call was
  guaranteed a hit".

## v0.1.0

- Initial release. `dscache.wrap()` transparently records per-request context-
  cache usage to a local ledger; `dscache report` prints the HIT/PARTIAL/MISS
  table with DeepSeek two-tier pricing; `dscache suggest` points at the worst
  bust; `dscache demo` writes a sample ledger so the report runs without an API
  key.
