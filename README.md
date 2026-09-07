# Enterprise AI Governance Sandbox

This project is a comprehensive AI Governance system designed to provide a secure, bi-directional proxy for Large Language Model (LLM) interactions. It enforces strict compliance, masks Personally Identifiable Information (PII), blocks toxic content, and provides a full administrative dashboard for auditing and configuration.

## Architecture Overview

The system consists of three main components:

1.  **Backend (`FastAPI`)**: A Python server that orchestrates the entire governance workflow, including the Ingress/Egress pipelines, PII scanning with Microsoft Presidio, and toxicity detection.
2.  **Frontend (`React`)**: A modern web interface for testing the guardrails, managing rules, and monitoring threats detected by the system.
3.  **AI Engine (`Ollama`)**: Utilizes locally-hosted LLMs to power the chat agent and other AI-driven features.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python**: Version 3.9 or higher.
- **Node.js**: Version 18 or higher, along with `npm`.
- **Ollama**: Download and install from https://ollama.com/.

---

## Setup and Running the Application

Follow these steps to get the full application running.

### 1. Backend Setup

The backend is a FastAPI server that runs the core governance logic.

```bash
# 1. Navigate to the project root directory
cd d:\PoC_Workspaces\AI-Governance-version2

# 2. Create and activate a Python virtual environment
python -m venv venv
.\venv\Scripts\activate  # On Windows
# source venv/bin/activate # On macOS/Linux

# 3. Install the required Python packages
pip install -r requirements.txt

# 4. Run the database setup script (first time only)
# This will create the initial SQLite database and tables.
python database.py

# 5. Set the API keys guarding every endpoint (see "Access control" below) --
# the app will start on the shipped development keys without this, but /system_status
# will report it and no real deployment should run on them.
export API_KEYS='{"<your-key>": {"name": "ops", "role": "super_admin"}}'   # macOS/Linux
# $env:API_KEYS = '{"<your-key>": {"name": "ops", "role": "super_admin"}}'  # Windows PowerShell

# 6. Run the FastAPI server
uvicorn api:app --reload
```

The backend API will now be running at `http://localhost:8000`. On startup it runs a
guardrail self-test -- if a guard is enabled in `pii_rules.json` but its model failed to
load, the console prints what's wrong and `GET /system_status` reports `"degraded"`; every
request is refused rather than passed through unchecked while a guard is unavailable.

### Access control

Every endpoint requires an `X-API-Key` header, mapped to a role in `config.json`'s
`API_KEYS` (or, preferably, the `API_KEYS` environment variable so real keys never enter
version control):

| Role | Can do |
|---|---|
| `super_admin` | Everything, including changing guardrail configuration |
| `admin_pii` | Read rules, alarms, analytics -- cannot change configuration |
| `caller` | Use `/chat`, `/demo_chat`, `/query_db`, `/govern_ai` |

`config.json` also carries `ENTITLEMENTS` -- which database record IDs each principal may
read through a tool call (`"*"` for unrestricted) -- and `EXPOSE_RAW_OUTPUT`, which must be
explicitly enabled (and still requires an admin role) before any endpoint returns the
model's unmasked text alongside the masked one.

### 2. Ollama LLM Setup

The application requires local LLMs to be served by Ollama.

```bash
# 1. Pull the required models
# The default model for general chat
ollama pull phi3

# The model for the "Toxic Test" mode in the chat
ollama pull dolphin-phi

# The model for suggesting code/regex in the admin sandbox
ollama pull codellama
```

Ensure the Ollama application is running in the background.

### Guardrail models

Two more models load automatically the first time the backend starts (via
`transformers`/`torch`, already pulled in by `requirements.txt`) -- no separate download
step, but the first run fetches them from Hugging Face, so it takes longer than
subsequent starts:

- **Toxicity** (`unbiased` Detoxify) -- was already part of the project.
- **Prompt/SQL injection** (`protectai/deberta-v3-base-prompt-injection-v2`) -- new. It
  flags phrasings no admin-authored pattern anticipated; a classifier-only hit is logged
  for review rather than blocked inline, since a model opinion alone was found to reject
  ordinary phrasing like "cancel order number 9999" (see `injection_guard.py`'s notes).
  A deterministic pattern match still blocks the request immediately.

### 3. Frontend Setup

The frontend is a React application built with Vite.

```bash
# 1. Open a new terminal and navigate to the frontend directory
cd d:\PoC_Workspaces\AI-Governance-version2\frontend

# 2. Install the node modules
npm install

# 3. Start the development server
npm run dev
```

The frontend will now be running and accessible at `http://localhost:5173` (or another port if 5173 is busy). You can open this URL in your browser to use the application.

---

## Running the tests

```bash
pip install -r requirements.txt   # pytest and httpx are included
pytest tests/ -q
```

The suite runs against a temporary working directory seeded with a copy of
`pii_rules.json` and `test_cases.json`, so it never touches the project's own alarms,
audit log, or rules -- and needs no running Ollama server (model calls are stubbed).
