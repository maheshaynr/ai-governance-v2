# Enterprise AI Governance Shield
## Final Implementation Plan & Architectural Reference

This document serves as the technical blueprint and final implementation plan for the AI Governance Shield. It details the dual-layer architecture, component responsibilities, and data flows designed to govern, mask, and audit AI ecosystem traffic.

---

## 1. Architectural Philosophy

The AI Governance Shield operates as a centralized **Enterprise AI Gateway**. All traffic flowing between users, databases, and large language models is routed through this proxy. The architecture relies on two distinct layers of protection to balance extreme low-latency performance with semantic deep-understanding.

### Layer 1: The Deterministic Firewall (Frontline)
*   **Technology**: Microsoft Presidio, SpaCy (`en_core_web_lg`), SciSpaCy (`en_ner_bc5cdr_md`).
*   **Function**: Intercepts structured and recognizable sensitive data (PII, PHI, Financials) using lightning-fast regex, mathematical checksums (e.g., Verhoeff for Aadhaar, Luhn for Credit Cards), and standard Named Entity Recognition (NER).
*   **Action**: Automatically applies a destructive `<MASK>` (e.g., `<PERSON>`, `<CREDIT_CARD>`) before the data reaches its destination.

### Layer 2: The Semantic Watchdog (Safety Net)
*   **Technology**: Local LLM (`phi-4-mini` via Ollama).
*   **Function**: Operates asynchronously in the background. It reads the *raw*, unmasked text and semantically analyzes the context to identify complex or malformed sensitive data that slipped past Layer 1 (e.g., an invalid credit card number being discussed as a payment method).
*   **Action**: Does not block the real-time chat, but silently generates a **Threat Alarm** for administrative review.

---

## 2. Core Components (Backend)

### `api.py` (The Central Gateway)
*   **Framework**: FastAPI
*   **Responsibilities**:
    *   Initializes the multi-model NLP pipeline.
    *   Hosts the `apply_egress_guardrail` function (the universal chokepoint for all data).
    *   Spawns `BackgroundTasks` for the Layer 2 Watchdog.
    *   Serves the Agentic Chatbot (`/chat`), routing `<FETCH_DB:ID>` tool calls to the database and feeding results back to the LLM.
    *   Exposes endpoints for the Admin UI to dynamically update rules, alarms, and configurations.

### `pii_rules.json` (Dynamic Configuration)
*   **Function**: A live JSON store containing custom Regex patterns and confidence scores. 
*   **Advantage**: Rules can be toggled `is_active: true/false` directly from the UI, immediately updating the Presidio Analyzer registry in `api.py` without requiring a server reboot or code deployment.

### `audit_logger.py` & `governance_audit.json`
*   **Function**: The ultimate source of truth for Shadow AI oversight.
*   **Mechanics**: Cryptographically hashes (SHA-256) all incoming raw text to enforce data minimization. It logs the exact timestamp, hashed input, and the final masked rewrite, providing an immutable record of all ecosystem AI traffic.

### `diff_engine.py` & `llm_watchdog.py`
*   **Function**: The operational brain of Layer 2. 
*   `llm_watchdog.py` prompts the local `phi-4-mini` model to extract a JSON list of leaked entities based on semantic context.
*   `diff_engine.py` compares the entities found by Layer 2 against the entities caught by Layer 1. If Layer 2 found something new, it generates an entry in `alarms.json` with a contextual snippet and reason.

### `custom_recognizers.py`
*   **Function**: Houses advanced algorithmic logic.
*   **Example**: The `AadhaarRecognizer` implements the Verhoeff algorithm to mathematically validate 12-digit Indian identities, drastically reducing false positives on random 12-digit order numbers.

---

## 3. Core Components (Frontend)

The frontend is a React.js application offering three distinct interfaces:

### Analytics Dashboard (`AnalyticsDashboard.jsx`)
*   Provides a high-level executive view of the Governance Shield's performance.
*   Displays real-time KPIs (Total Tokens Guarded, Threats Caught, Active Rules, and Alarms).
*   Features geographic origin maps and threat-category bar charts.

### The Sandbox & Testing Suite (`Dashboard.jsx` & `test_cases.json`)
*   An interactive environment to simulate DB queries and Chatbot interactions.
*   Displays a side-by-side comparison of **🔴 Raw LLM Output (Leaking PII)** vs. **🟢 Shielded Output (Safe)**.
*   Executes predefined test cases covering HIPAA, GDPR, Financial, and Authentication leaks.

### Admin Command Center (`AdminConfig.jsx`)
*   The control plane for DLP engineers.
*   Allows creation, modification, and toggling of active PII rules.
*   Provides an interface to review **Layer 2 Threat Alarms** and automatically invoke the LLM to generate precise Regex solutions to fix "False Dismissals".

---

## 4. Future Expansion Mapping

Based on the 6 Pillars of AI Governance, this architecture is primed for expansion:

1.  **Data Leakage**: Fully implemented via Egress Guardrail.
2.  **Shadow AI**: Fully implemented via Central API Routing and Audit Logging.
3.  **Prompt Injection**: *Planned.* Implement an Ingress Guardrail to scan incoming user prompts using the existing dual-layer philosophy.
4.  **Hallucinations**: *Planned.* Expand the Watchdog to cross-reference AI output against retrieved DB context for factual fidelity.
5.  **Bias & Fairness**: *Planned.* Prompt the Watchdog to score AI output for demographic neutrality.
6.  **Model Drift**: *Planned.* Aggregate the Audit Logs into time-series graphs to monitor underlying model degradation.
