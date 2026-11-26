import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.budget import DailyBudget, estimate_cost_usd
from app.fakes import FakeProvider
from app.main import StreamSettings, create_app
from app.stream import explain_stream

pytestmark = pytest.mark.anyio   # run async tests on asyncio via the AnyIO plugin

FAST = dict(ttft_timeout_s=0.2, total_timeout_s=2.0, max_output_tokens=50)


async def collect(gen):
    return [ev async for ev in gen]


def budget(limit=1.0):
    return DailyBudget(limit_usd=limit, today=lambda: date(2026, 11, 16))


def sse_events(response):
    """Parse a text/event-stream body into (event, data) pairs."""
    events, name, data = [], None, []
    for line in response.iter_lines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif line == "" and data:
            events.append((name, json.loads("\n".join(data))))
            name, data = None, []
    return events


async def test_happy_path_streams_meta_tokens_done():
    p = FakeProvider("primary", ["Liability ", "is ", "capped."])
    events = await collect(explain_stream("prompt", [p], tenant="t1", budget=budget(), **FAST))
    assert [e.kind for e in events] == ["meta", "token", "token", "token", "done"]
    assert "".join(e.data["text"] for e in events if e.kind == "token") == "Liability is capped."


async def test_slow_first_token_falls_back_to_second_provider():
    slow = FakeProvider("primary", hang=True)
    backup = FakeProvider("backup", ["ok"])
    events = await collect(explain_stream("prompt", [slow, backup], tenant="t1", budget=budget(), **FAST))
    assert events[0].kind == "meta" and events[0].data["provider"] == "backup"
    assert events[-1].kind == "done"


def test_estimate_uses_max_output_tokens():
    p = FakeProvider("p", price_in_per_mtok=2.0, price_out_per_mtok=10.0)
    prompt = "x" * 400                      # the fake counts 1 token per 4 characters: 100 tokens
    assert estimate_cost_usd(p, prompt, 300) == pytest.approx((100 * 2.0 + 300 * 10.0) / 1_000_000)


def test_http_endpoint_speaks_server_sent_events():
    app = create_app([FakeProvider("primary", ["Hello"])], budget(), StreamSettings(**FAST))
    client = TestClient(app)
    with client.stream("POST", "/v1/clauses/explain", headers={"X-Tenant-ID": "bayyina"},
                       json={"clause_text": "يلتزم المورد بتعويض المشتري", "language": "ar"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = sse_events(r)
    assert [name for name, _ in events] == ["meta", "token", "done"]
