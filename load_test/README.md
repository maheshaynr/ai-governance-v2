# Load Test Harness — User Guide

A standalone client for load testing the AI Governance API's guardrail concerns --
three isolated (one concern each) and one combined. All request content is static,
hand-written in `messages.json` — nothing is pulled from the database or generated
by an LLM at test time.

## What each scenario actually tests

| Scenario | Target | What it exercises |
|---|---|---|
| `pii` | `POST /govern_ai` on the app | Pure guardrail masking — no LLM call. Sends PII-bearing text (some designed to mask, some designed as known coverage gaps or false-positive checks) and checks the response against an expected outcome. |
| `toxicity` | `POST /demo_chat` (mode=`toxic`) on the app | The ingress toxicity check, which runs *before* any LLM call and short-circuits toxic input. Includes jailbreak-framed attempts and a false-positive check. |
| `llm` | Ollama directly (`/api/chat`), **bypassing the app entirely** | Raw model responsiveness — no guardrails, no DB, no tool-call routing. Useful because routing this through the app's two-hop tool-call flow conflated app overhead with model latency and risked client timeouts. |
| `e2e` | `POST /govern_ai` on the app, **plus Ollama directly if `--e2e-llm` is set** | The **combined** flow — same guardrail check as `pii` (PII masking + toxicity flag). By default this is guardrail-only, fast, LLM-free. Pass `--e2e-llm` to also make a real, timed call straight to Ollama, so measured latency includes actual LLM inference, not just guardrail overhead. Deliberately two separate calls rather than routing through `/demo_chat`, since that endpoint blocks toxic messages *before* the LLM (so toxic messages would never include LLM time) and would require trusting a small local model to echo PII back faithfully. Zero DB involvement either way — see the caveats below. |

Every message in `messages.json` carries a `size` (small/medium/large) and `technique` tag, and (for `pii`/`toxicity`/`e2e`) an `expect` block the client checks the real response against — so a run reports both **latency** and **correctness**, not just speed. `e2e` has 100 messages (vs. a handful for the other scenarios) — PII-only, toxic-only, both combined, a clean baseline, and a few large documents burying both.

**Two caveats on `e2e`:**
1. `/govern_ai` schedules an async background LLM watchdog task after responding, if `enable_llm_watchdog` is on in `pii_rules.json` (it is, by default) — separate from `--e2e-llm`'s direct call, never affects measured latency, but is additional real (non-blocking) Ollama traffic. Same caveat applies to `pii`, since it shares the endpoint.
2. **With `--e2e-llm` set, every single `e2e` request makes a real LLM call**, same cost profile as the `llm` scenario (30-120+ seconds per request on a CPU-only model). Running all 100 messages in burst mode with low concurrency will take a long time — start small (`--requests 5 --concurrency 2`) before scaling up, same advice as `llm`/`toxicity`.

## Prerequisites

- Python virtual environment with the project's dependencies installed (`.venv` or `venv` in the project root already has everything needed — `requests`, plus whatever the app itself needs since `client.py` imports `config.py`).
- For `pii`/`toxicity` scenarios: the FastAPI backend running.
- For any scenario that talks to an LLM (`toxicity` when a message isn't blocked, `llm` always): Ollama running with the model(s) configured in `config.py` (or passed via `--ollama-model`) pulled and available.

## 1. Start the backend

From the project root, in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api:app --reload
```

Wait for `Presidio, Database, and RAG Engine loaded successfully.` before sending traffic — first load is slow (SpaCy/SciSpaCy/Presidio/Detoxify/RAG models all load into memory).

If `uvicorn` resolves to the wrong Python (e.g. `ModuleNotFoundError: No module named 'detoxify'`), your shell probably isn't using the venv. Run it explicitly instead:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --reload
```

The `llm` scenario doesn't need the backend running at all — it talks straight to Ollama.

## 2. Run the load test

Always invoke via the venv's Python to guarantee the right interpreter:

```powershell
.\.venv\Scripts\python.exe load_test\client.py --scenario pii --requests 5 --concurrency 2
```

### Sanity-check each scenario first, at low volume

```powershell
.\.venv\Scripts\python.exe load_test\client.py --scenario pii --requests 5 --concurrency 2
.\.venv\Scripts\python.exe load_test\client.py --scenario toxicity --requests 5 --concurrency 2
.\.venv\Scripts\python.exe load_test\client.py --scenario llm --requests 5 --concurrency 2
.\.venv\Scripts\python.exe load_test\client.py --scenario e2e --requests 5 --concurrency 2
.\.venv\Scripts\python.exe load_test\client.py --scenario e2e --requests 5 --concurrency 2 --e2e-llm  # also include a real LLM call
```

### Full run — all four scenarios, one after another

```powershell
.\.venv\Scripts\python.exe load_test\client.py --scenario all
```

```powershell
.\.venv\Scripts\python.exe load_test\client.py --scenario all --requests 30 --concurrency 8
```

Scenarios never run concurrently with each other — `all` means sequential, so `--concurrency` only ever caps in-flight requests *within* whichever scenario is currently running.

### `llm` scenario — pointing at a specific model/Ollama instance

```powershell
.\.venv\Scripts\python.exe load_test\client.py --scenario llm --ollama-model tinyllama-cpu
.\.venv\Scripts\python.exe load_test\client.py --scenario llm --ollama-url http://127.0.0.1:11434/api/chat --ollama-model phi4-mini-cpu
```

### Timed mode — fire at a fixed rate for a fixed duration

By default the client runs in **burst mode**: it submits `--requests` messages immediately and drains them as fast as `--concurrency` workers allow — there's no pacing. Pass `--rate` to switch to **timed mode** instead: it fires one new request every `1/--rate` seconds, for `--duration` seconds, reusing/cycling messages from the bank at random for as long as the run continues. `--concurrency` still caps how many requests can be in flight at once — if responses are slower than the requested rate implies (very possible on the `llm`/`toxicity` scenarios), extra dispatches simply queue up behind that cap rather than piling on unbounded.

Example: 1 request per second for 1 minute —

```powershell
.\.venv\Scripts\python.exe load_test\client.py --scenario pii --rate 1 --duration 60
```

2 requests per second for 2 minutes, capped at 5 concurrent in flight —

```powershell
.\.venv\Scripts\python.exe load_test\client.py --scenario llm --rate 2 --duration 120 --concurrency 5
```

All four scenarios, each timed independently (1 req/sec for 1 minute, run one after another — since scenarios always run sequentially, this takes ~4 minutes total, not 1) —

```powershell
.\.venv\Scripts\python.exe load_test\client.py --scenario all --rate 1 --duration 60
```

`--duration` requires `--rate`. If you use `--rate` without `--duration`, you must also pass `--requests` as a cap (otherwise it would run forever). The summary line reports both the *requested* rate and the *actual achieved* rate, so a gap between the two (e.g. asking for 2/sec on the `llm` scenario when responses take 60+ seconds each) is visible immediately rather than hidden. The rate, concurrency, and duration used for a run are also written into every row of the output CSV (`rate_rps`, `concurrency`, `duration_s` columns), so results stay traceable to the config that produced them even after the fact.

## 3. Flag reference

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | `all` | `pii`, `toxicity`, `llm`, `e2e`, or `all` (sequential) |
| `--requests` | `15` in burst mode, unbounded in timed mode | Burst mode: total requests per scenario. Timed mode: optional extra cap on top of `--duration`. |
| `--concurrency` | `5` | Max requests in flight at once, per scenario |
| `--rate` | *(unset = burst mode)* | Requests/second — setting this switches to timed mode |
| `--duration` | *(unset)* | Timed mode only: how long to keep dispatching, in seconds |
| `--base-url` | `http://127.0.0.1:8000` | App base URL (used by `pii`/`toxicity`, and the alarm-count check) |
| `--timeout` | `120.0` | Per-request timeout, seconds — raise this for large-content or slow-model runs |
| `--out-dir` | `load_test\results` | Where result CSVs are written |
| `--ollama-url` | from `config.py`'s `OLLAMA_URL` | Direct Ollama endpoint, used by `llm` and `e2e` (when `--e2e-llm` is set) |
| `--ollama-model` | from `config.py`'s `DEFAULT_LLM_MODEL` | Model name, used by `llm` and `e2e` (when `--e2e-llm` is set) |
| `--e2e-llm` | off | `e2e` scenario only: also make a real, timed call straight to Ollama, so measured latency includes LLM inference, not just the guardrail check |

Run `.\.venv\Scripts\python.exe load_test\client.py --help` for the live version of this table.

## 4. Reading the output

Console, per scenario:

```
=== Scenario: pii (15 requests, concurrency 5) ===
  Requests:     15  (errors: 0)
  Pass/Fail:    12 passed / 3 failed  (of 15 with an expectation)
  Latency ms:   min=45 mean=210 p50=180 p90=410 p95=480 max=520
  By size: ...
  By technique: ...
  Failed expectations: ...
  Throughput:   4.2 req/s (wall clock 3.6s)
  Alarms:       12 -> 12 (+0)
  CSV written:  load_test/results/pii_20260828_140501.csv
```

- **Pass/Fail** is checked against each message's `expect` block in `messages.json` — a message tagged as a known coverage gap (e.g. `baseline_gap_no_rule`) is *expected* to come back unmasked, so that's a pass, not a bug. Only entries under **Failed expectations** need a look.
- **By size / By technique** breaks latency and pass/fail down further — this is where "does a 1000-word document cost more than a one-liner" or "does jailbreak framing get past the toxicity guard" actually show up.
- **Alarms** is a before/after count from `GET /alarms`, bookending the run — cross-checkable against the Analytics tab in the UI. Always shows `+0` for the `llm` scenario since it bypasses the app's guardrails entirely.
- One row per request is written to `load_test/results/<scenario>_<timestamp>.csv` (columns: message id, technique, size, input size, api status, latency, pass/fail, error, plus `response_chars` for `llm`/`e2e`, `toxic_flagged` for `e2e`, and `app_error_detail` — the actual exception text whenever the app itself returns `status: "error"` in an otherwise-valid response, distinct from `error`, which is this client's own transport-level failures).

## Known things to expect, not bugs

- **The `llm` and `toxicity` scenarios can be very slow (30-120+ seconds per request)** if the configured Ollama model is CPU-only — this is a real property of the backend, not a client issue. Raise `--timeout` accordingly, or expect some requests to time out and show up as `error` rows (the client handles this gracefully — one slow/failed request never crashes the run).
- **`alarms.json` / `alarms_archive.json` grow with every run** that reaches the real backend, since several messages are deliberately designed to trigger guardrail alarms (buried PII, coverage gaps, jailbreak toxicity). Clear `alarms.json` via the Admin UI between runs if you don't want load-test noise mixed into real alarm review.
- **`load_test/` is currently caught by a pre-existing corrupted line in `.gitignore`** (unrelated to this harness — predates it). New files under `load_test/` need `git add -f` to be tracked; `load_test/results/` is deliberately ignored (see `.gitignore`) so generated CSVs don't get committed.
