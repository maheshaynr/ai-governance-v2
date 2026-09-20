# AI Guardrail — Onboarding / Hand-off

This is the **AI Guardrail** (repo name `AI-Governance-version2` locally, GitHub
`maheshaynr/ai-governance-v2`) — an enterprise AI governance sandbox that sits as a
bi-directional proxy in front of local LLMs, enforcing PII/PHI/financial-data masking,
toxicity/injection blocking, DPDP-style consent gating, and agent identity/activity
governance for external systems that call it.

Latest work is on branch **`version-7`** — start there.

## 1. What this actually is (read this before touching code)

Three cooperating pieces, only one of which lives in this repo:

1. **This repo (AI Guardrail)** — FastAPI backend (`api.py`) + React admin/chat frontend
   (`frontend/`). Masks PII, blocks toxic/injected content, brokers tool calls
   (`tool_broker.py`), and now also runs an **Agent Governance Layer** (agent identity
   registration, activity log, compliance events — see §6).
2. **The DPDP Engine** — a **separate service**, not in this repo. This app calls it over
   HTTP (`dpdp_client.py`) for consent decisions (`POST /v1/decisions/check`). Its own
   design docs (`DPDP_GUARDRAIL_INTEGRATION_DESIGN.md`, `API_INTEGRATION.md`,
   `GOVERNANCE_LAYER_MOVEMENT_PLAN.md`) live in that other project's directory
   (`AI_DPDP_Engine` alongside this one on the original machine) — **you need access to
   a running instance of it**, or nothing consent-gated will work (see §4).
3. **External client apps** — e.g. a VOXA Android app (Swiggy + Yahoo Finance skills) and
   a JioCare Helper app, which call *this* app's `/v1/agent/*` and `/guardrail_validate`
   endpoints. Not part of this repo either; mentioned so you know why those endpoints
   exist and are deliberately left open (no login key required — see §6).

**Read `Implementation_Plan/Agent_Governance_Layer_Design.md` next** — it's the fullest,
most current design reference in this repo (data model, exact wire contracts, rationale,
and a worked VOXA integration example). `Implementation_Plan/AI_Governance_Architecture.md`
and `governance_policies/data_standards.md` cover the original PII-masking architecture.

## 2. Prerequisites

- Python 3.11 (a `.venv` is expected at the repo root — not committed, you create it)
- Node.js + npm (for `frontend/`)
- [Ollama](https://ollama.com), running locally, with two CPU-pinned models pulled:
  ```
  ollama create phi4-mini-cpu -f Modelfile.cpu
  ollama create tinyllama-cpu -f Modelfile.tiny-cpu
  ```
  (`Modelfile.cpu`/`Modelfile.tiny-cpu` are at the repo root — they just pin `phi4-mini:3.8b`
  / `tinyllama:latest` to `num_gpu 0`.)

## 3. First-time setup

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python database.py                 # seeds cohort.db (customers, spenders, notices, consents)
cd frontend && npm install && cd ..
copy frontend\.env.example frontend\.env   # only if it doesn't already exist
```

First backend startup is slow (~30-60s) — Presidio, spaCy (`en_core_web_lg` +
`en_ner_bc5cdr_md`), Detoxify, and the prompt-injection classifier all download/load into
memory on import. `governance.db` (Agent Governance Layer storage) is created
automatically on first `api.py` import too — no separate init step.

## 4. Configuration — the one thing that will NOT work out of the box

`config.json` (repo root, **gitignored-adjacent but not actually gitignored — don't
commit real secrets into it**) currently has, on the source machine:

```json
{
  "OLLAMA_URL": "http://localhost:11434/api/chat",
  "DEFAULT_LLM_MODEL": "phi4-mini-cpu",
  "TOXIC_LLM_MODEL": "tinyllama-cpu",
  "CODING_LLM_MODEL": "phi4-mini-cpu",
  "DPDP_BASE_URL": "http://localhost:8002",
  "DPDP_SERVICE_TOKEN": "dev-ai-guardrail-token"
}
```

`DPDP_BASE_URL`/`DPDP_SERVICE_TOKEN` point at a DPDP Engine instance on the **original**
machine. On a new desktop, either:
- Stand up your own DPDP Engine instance and point `DPDP_BASE_URL` at it, or
- Point at the original machine's DPDP Engine over the network (if reachable), or
- Leave `DPDP_BASE_URL` empty — the app **fails closed** on anything consent-gated
  (`dpdp_client.py` refuses to even attempt a call against an empty URL) rather than
  erroring, so the rest of the app still runs; only the Consent Gate (`tool_broker.py`)
  and the `/guardrail_validate` payment path will show `consent_required`/
  `PAYMENT_DECLINED` for everything.

If you don't have the DPDP Engine's own docs handy, ask whoever owns it for
`API_INTEGRATION.md` — it has the exact schema, test subjects (`U19883`/`U55442`/
`U88778`), and auth token convention. Do **not** guess a URL/token.

## 5. Running it

```
start_backend.bat     # uvicorn api:app --host 0.0.0.0 --port 8000
start_frontend.bat     # npm run dev, Vite picks 5173 (or next free port)
```
(or `start_all.bat` for both). Backend binds `0.0.0.0` deliberately, so other devices on
the same LAN can reach it at `http://<this-machine's-IP>:8000` — needs a Windows Firewall
inbound rule for TCP 8000 if you want that (`New-NetFirewallRule -DisplayName "AI
Guardrail Backend (8000)" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`,
elevated PowerShell).

**Authentication is ON.** The frontend shows a login gate. Dev placeholder keys (from
`config.py`, override via `API_KEYS` env var for anything real):
| Key | Role |
|---|---|
| `dev-super-admin-key` | `super_admin` — unrestricted |
| `dev-pii-admin-key` | `admin_pii` — views + record-level actions, not guardrail-config changes |
| `dev-caller-key` | `caller` — Chat Bot only, and entitled to customer record `101` only |

**Gotcha worth knowing up front**: the `caller` role's entitlement (`config.py`'s
`ENTITLEMENTS`) only covers customer `101`. The newer DPDP demo customers (`19883`,
`55442`, `88778`, seeded in `database.py`) are only reachable by `super_admin`/`admin_pii`
— a `caller`-role login will get an entitlement refusal on those before ever reaching the
DPDP consent check, which can look like "the DPDP integration is broken" when it isn't.

## 6. Agent Governance Layer — what's new since the base architecture

A second admin page, "Agent Governance" (top nav, next to Admin Configuration), with 4
tabs: Registered Agents, Activity Log, Compliance Events, Stats. Backs external systems
(VOXA, etc.) that register their own identity (`POST /v1/agent/register`) and get a
per-agent secret — **separate from the human `X-API-Key` login above**. The admin
list/revoke/stats routes under `/v1/agent/*` DO require human RBAC (`admin_pii`/
`super_admin`); the registration/decision-check/activity-log routes external agents
actually call do NOT — they're deliberately open, verified instead by their own
`X-Agent-Id` + secret. Full contract: `Implementation_Plan/Agent_Governance_Layer_Design.md`
§4.1.

## 7. Tests

```
pytest tests/ -q
```
201 tests, ~3-7 minutes (the heavy ML models load once per session via a session-scoped
fixture, not per-test). All tests run against a temp working directory (`conftest.py`)
seeded with copies of `pii_rules.json`/`test_cases.json` — they never touch your real
`cohort.db`/`governance.db`/`alarms.json`.

## 8. Things to know before changing anything

- **Don't re-introduce a shared/global auth bypass.** RBAC was removed once already (by
  explicit request), then fully restored later in the same project. `auth.py`'s
  docstring explains the current enforcement; don't add a new
  `principal = auth.ANONYMOUS_PRINCIPAL`-style shortcut without understanding why that
  was reverted.
- **The Admin "Consents" ledger tab is local-only**, backed by `consent.py`'s own SQLite
  table — it does **not** reflect the DPDP Engine's actual consent state (a known,
  previously-flagged architectural gap, not a bug to silently "fix" by guessing at an
  API the DPDP Engine doesn't expose).
- **Never log raw PII, prompts, or model output anywhere** — `audit_logger.py`,
  `governance_db.py`'s activity log, and the DPDP Engine's own compliance events all
  enforce "metadata/hash only, never content" as a hard rule throughout this codebase.
  Follow that pattern for anything new.
- `cohort.db` and `governance.db` are gitignored — local runtime state, recreated
  automatically. If either looks stale/wrong, it's safe to delete and let
  `database.py`/`api.py`'s own init functions reseed them, rather than hand-editing.
