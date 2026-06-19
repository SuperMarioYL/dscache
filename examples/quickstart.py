"""Two-line integration: wrap your DeepSeek client, run your loop, read the report.

Run this without an API key — it uses a tiny fake client so you can see the
ledger fill up. In real use, pass your actual ``OpenAI(base_url="...deepseek...")``
client to ``dscache.wrap`` and then run ``dscache report`` in your terminal.
"""

import dscache


class _FakeUsage:
    def __init__(self, cached, miss):
        self.prompt_tokens = cached + miss
        self.prompt_cache_hit_tokens = cached
        self.prompt_cache_miss_tokens = miss


class _FakeResp:
    def __init__(self, i, cached, miss):
        self.id = f"chatcmpl-{i:03d}"
        self.model = "deepseek-chat"
        self.usage = _FakeUsage(cached, miss)


class _Completions:
    def __init__(self):
        self.i = 0

    def create(self, **kwargs):
        self.i += 1
        # third call busts the cache
        cached, miss = (4120, 80) if self.i != 3 else (120, 4080)
        return _FakeResp(self.i, cached, miss)


class _Chat:
    completions = _Completions()


class _FakeClient:
    chat = _Chat()


# ---- the only two lines you add to your own code ----
client = dscache.wrap(_FakeClient())
# -----------------------------------------------------

for _ in range(5):
    client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "system", "content": "You are a coding agent."}],
    )

print("Ledger written to .dscache/ledger.jsonl — now run:  dscache report")
