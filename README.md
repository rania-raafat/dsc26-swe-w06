# dsc26-swe-w06 · Bayyina clause explainer with a budget

DSC Summer Internship 2026 · Software Engineering track · Week 6
**Python 3.12 · FastAPI 0.141.1 (`fastapi.sse`) · AnyIO 4.15.1 · pytest 9.1.1** · expected time 3–4 hours

## Scenario

Bayyina's junior lawyers want a plain explanation of a clause, streamed while they read the
contract. The firm has two providers: a strong primary and a cheaper backup. Yasmine's finance
colleague has set a daily AI budget per client matter, and the review screen must never hang.
You build the streaming core and the endpoint around it. No real model is involved: DSC
provides fake providers (`app/fakes.py`) that behave like real ones on a bad day — slow, prone
to hanging, prone to failing before or during an answer. There is no network call and no API
key anywhere in this task.

## Set up

```bash
# your repository must be named exactly dsc26-swe-w06, public, in your own GitHub account
git init -b main
uv venv --python 3.12
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt  # pinned versions; do not change them
pytest -q                           # public tests: they fail until you build the task
```

Run the API by hand with `uvicorn` once `create_app` works, for example from a short script
that builds `create_app([FakeProvider("primary")], DailyBudget(1.0))`, and watch tokens arrive
with `curl -N -X POST localhost:8000/v1/clauses/explain -H 'X-Tenant-ID: bayyina' -H 'Content-Type: application/json' -d '{"clause_text":"The Supplier shall indemnify the Buyer.","language":"en"}'`.

## Files

```
app/__init__.py       empty
app/providers.py      given: the LLMProvider protocol, ProviderError, build_prompt (do not edit)
app/fakes.py          given: FakeProvider for your own testing (do not edit; the grader
                      replaces this file with its own copy with different names, prices and delays)
app/budget.py         you write: estimate_cost_usd, actual_cost_usd, DailyBudget
app/stream.py         you write: Event, explain_stream
app/main.py           you write: StreamSettings (given) and create_app
tests/test_public.py  the public tests (keep tests/__init__.py so `pytest -q` finds app/)
AI_USAGE.md           required, see the end of this file
requirements.txt      pinned versions; the grader has exactly these and no network
```

## What to build

### 1. `app/budget.py`

- `estimate_cost_usd(provider, prompt, max_output_tokens) -> float`: the worst case —
  `(count_tokens(prompt) * price_in_per_mtok + max_output_tokens * price_out_per_mtok) / 1,000,000`.
- `actual_cost_usd(provider, prompt, output_tokens) -> float`: the same formula with the
  tokens actually produced.
- `class DailyBudget(limit_usd: float, today: Callable[[], date])` with:
  - `remaining(tenant) -> float`
  - `try_reserve(tenant, amount) -> bool`: reserves the amount and returns `True` only if
    `amount <= remaining(tenant)`; returns `False` and reserves nothing otherwise.
  - `settle(tenant, reserved, actual) -> None`: replaces a reservation with the actual cost.
  - Budgets are per tenant **per `today()` date**; a new date starts from zero (so changing
    what `today()` returns resets every tenant's spend).

### 2. `app/stream.py`

`Event` (already defined for you: a frozen dataclass with `kind: str` and `data: dict`) and

```python
async def explain_stream(prompt: str, providers: Sequence[LLMProvider], *, tenant: str,
                         budget: DailyBudget, ttft_timeout_s: float, total_timeout_s: float,
                         max_output_tokens: int) -> AsyncIterator[Event]: ...
```

Rules, in order:

- Try providers in the given order. Before calling each, reserve its `estimate_cost_usd`; if
  the tenant cannot afford it, **skip it without calling it** and try the next.
- Wait at most `ttft_timeout_s` (and never past the overall deadline) for the first token. On
  a timeout, a `ProviderError`, or an empty stream (no token at all), settle that provider's
  reservation at 0 and move to the next provider.
- On the first token, emit `Event("meta", {"provider": name})`, then `Event("token", {"text": ...})`
  for every token, including the first.
- **After the first token, never switch provider.** A `ProviderError` now emits
  `Event("error", {"code": "upstream_interrupted", "partial": True})` and the generator stops.
- The whole call never runs past `total_timeout_s` measured from the start. When the deadline
  passes (waiting for the first token or a later one), emit
  `Event("error", {"code": "deadline_exceeded", "partial": <True iff any token was sent>})`
  and stop.
- On success (the provider's stream ends normally after producing at least one token), settle
  the reservation at the actual cost and emit
  `Event("done", {"provider": name, "output_tokens": n, "cost_usd": actual_cost})`.
- If every provider you could afford failed before producing a first token:
  `Event("error", {"code": "all_providers_failed"})`.
  If no provider was affordable in the first place (nothing was attempted):
  `Event("error", {"code": "budget_exhausted"})`.
- **Whatever happens** — success, every kind of failure, or the caller closing this async
  generator early (`aclose()` or simply abandoning it) — the provider's own stream must be
  closed (`await stream.aclose()`, directly or via `contextlib.aclosing`) and its reservation
  must be settled at the actual cost of whatever tokens it produced, exactly once.

Two traps the hidden tests catch: wrapping a `yield` inside `async with asyncio.timeout(...)`
inside an async generator (the timeout can fire while the *consumer*, not your code, is
running); and not closing the provider's generator explicitly, which leaves it generating
(and in a real system, billing) tokens nobody reads until garbage collection gets to it.

### 3. `app/main.py`

`StreamSettings` is given (`ttft_timeout_s=2.0`, `total_timeout_s=20.0`,
`max_output_tokens=400`). You write:

```python
def create_app(providers: Sequence[LLMProvider], budget: DailyBudget,
               settings: StreamSettings | None = None) -> FastAPI: ...
```

- `POST /v1/clauses/explain`. Header `X-Tenant-ID` (required, 1–64 chars). Body
  `{"clause_text": <1–8000 chars>, "language": "ar" | "en"}`. Build the prompt with
  `app.providers.build_prompt(clause_text, language)`.
- **Before streaming starts:** invalid input (missing/empty/too-long `clause_text`, an
  unknown `language`, a missing or too-long `X-Tenant-ID`) is a normal `422`. If the tenant
  cannot afford even the cheapest provider's worst-case estimate, a normal `429` with
  `application/problem+json` body `{"type": "/problems/budget-exhausted", "title": ..., "status": 429}`.
  **No provider is called** in either case.
- Otherwise, return a `text/event-stream` response (`fastapi.sse.EventSourceResponse`,
  yielding `fastapi.sse.ServerSentEvent(event=ev.kind, data=ev.data)` for each `Event` from
  `explain_stream`) with events named `meta`, `token`, `done` and `error`, each event's `data`
  serialised as JSON. **Once this response starts, the status code is 200 and cannot
  change** — anything that goes wrong after that point is one of `explain_stream`'s `error`
  events, never a different HTTP status.
- `create_app` returns a **new** app each time (no shared state between two apps built from
  the same `providers`/`budget` objects is fine — the budget and provider objects you were
  given are intentionally shared on purpose, so a per-tenant budget persists across calls).

## `AI_USAGE.md`

AI tools are allowed. Keep the three headings `## Tools`, `## What AI got wrong` and
`## In my own words`. Under `## In my own words`, answer in one or two sentences each,
without AI: "Why is it safe to switch provider before the first token and not after?" and
"Which checks did you put before the stream starts, and why could they not be error events
instead?"

## Public tests

`pytest -q` runs `tests/test_public.py` (4 tests, two of them `async def` run by the AnyIO
pytest plugin — already installed with AnyIO, no extra package or config needed). They fail on
the starter and pass on a correct solution. Passing them is necessary, not sufficient: the
hidden tests decide the score.

## How grading works

Push to `dsc26-swe-w06`, then press **Submit for grading** on DSC Hex (5 runs per task per
day). The grader overwrites `app/providers.py` and `app/fakes.py` with DSC's own copies
(different provider names, prices, token lists and delays from the ones you tested against —
do not special-case the public fake's name or behaviour), copies DSC's hidden tests into
`tests_hidden/`, removes any `conftest.py`/`pytest.ini` at the repository root, ignores pytest
settings in `pyproject.toml`/`setup.cfg`/`tox.ini`, and runs each hidden test with
`python -m pytest` from the repository root, network off, 10 s per test and 3 minutes in all.
Your own tests are not run by the grader. You see each hidden test's name, pass or fail, and a
short hint; never the test code.

| ID | Public name | What it checks | Weight |
|---|---|---|---|
| H01 | stream: meta, tokens, done in order | Event order and kinds; tokens concatenate to the provider's text; `done` has provider, token count and cost | 10 |
| H02 | http: valid SSE with named JSON events | Content type, event names, every `data` line parses as JSON, Arabic text survives intact | 8 |
| H03 | fallback: slow first token moves to the next provider | Over HTTP and directly; no tokens from the slow provider ever appear | 10 |
| H04 | fallback: failure before the first token moves on | `fail_before_first` and an empty token list | 6 |
| H05 | no switching after the first token | `fail_after_tokens=2` gives meta, two tokens, `upstream_interrupted` with `partial: true`; the backup is never called | 10 |
| H06 | deadline: the whole call stops on time | A slow stream with a short deadline ends with `deadline_exceeded` promptly after the deadline; also when the deadline passes during fallback | 8 |
| H07 | all providers failing ends with one error event | `all_providers_failed`, and nothing else is emitted | 5 |
| H08 | cost: estimate is exact and worst-case | Several prices, prompt lengths and caps, compared with the formula | 6 |
| H09 | budget: unaffordable providers are skipped, not called | The cheaper backup is used; the expensive provider's `calls` stays 0 | 8 |
| H10 | budget: settled at the actual cost | Remaining budget after a fallback and a success equals limit minus the actual cost; failed-before-first attempts cost nothing; `cost_usd` matches | 8 |
| H11 | budget exhausted is 429 before streaming | Problem document, provider never called; another tenant still served | 6 |
| H12 | budget resets on a new day | Changing `today()` restores the full limit | 5 |
| H13 | validation happens before any provider call | Empty or 8001-character clause, unknown language, missing tenant header: 422, `calls == 0` | 5 |
| H14 | closing the stream early closes the provider | Read two events, `aclose()` the generator: the provider's `closed` count is 1 and its reservation is settled | 5 |
| | | **Total** | **100** |

The hidden tests use DSC's own `FakeProvider` with different token lists, prices, delays and
names from the public ones, and a hidden test file that cannot import a name it needs fails
all of its own tests, so keep the names above exactly.

Late policy: ×1.0 within 72 hours of the session starting, ×0.6 for the following 7 days,
×0.5 after that. Your best attempt counts.
