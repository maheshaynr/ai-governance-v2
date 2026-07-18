# AI Governance Sandbox: Full System Implementation Plan

This document serves as the comprehensive implementation blueprint for the Enterprise AI Governance Sandbox. It details the complete architecture, the modules implemented, the data flow, and the security mechanisms designed to protect enterprise LLM interactions.

## 1. Goal Description
The objective of the AI Governance Sandbox is to provide a robust, bi-directional proxy between users and Local/Enterprise LLMs. The system enforces strict compliance (GDPR, HIPAA, Financial) by dynamically masking PII, blocking toxic/abusive content, and auditing all violations through a central administrative dashboard.

## 2. Core Architecture & Precedence

The architecture is built on a **Fail-Fast, Defense-in-Depth** model powered by FastAPI and a React frontend. 

1. **State Management (`pii_rules.json`)**: Acts as the absolute source of truth. Contains all regex rules, algorithmic verifiers, and category mappings.
2. **Ingress Pipeline (Inbound)**:
   * **Toxicity Guard (`detoxify`)**: Analyzes the raw prompt for 7 classes of toxicity (e.g., severe toxicity, identity attack). If threshold is breached, the request is hard-blocked.
   * **PII Guardrail (`Microsoft Presidio`)**: Scans for sensitive entities (e.g., SSN, Aadhaar, Credit Cards). Masks the data (e.g., `<CREDIT_CARD>`) to prevent leakage into the LLM context.
3. **Execution Engine (`Ollama / RAG`)**: Executes the clean, sanitized prompt against local models (`phi4-mini`) or performs SQL Database lookups.
4. **Egress Pipeline (Outbound)**:
   * **Toxicity Guard**: Ensures the AI has not hallucinated hateful or abusive content.
   * **PII Guardrail**: Ensures the AI does not leak unmasked sensitive database records back to the user.

## 3. Implemented Modules

### 3.1. The Administrative Dashboard (Frontend)
A React-based UI that provides granular control over the Governance Shield.
* **Modular Rule Configuration**: Split-pane layout for managing compliance modules independently.
  * **Categories**: GDPR, HIPAA, FINANCIAL, AUTHENTICATION.
  * **Rule Management**: Dynamic popup modal for adding/editing Custom Regex or Algorithmic (Python) rules.
  * **Live Toggling**: Admins can turn entire categories or individual rules on/off in real-time.
* **Toxicity Tuning**: UI sliders to adjust the confidence threshold (0.0 to 1.0) for the 7 toxicity classes.
* **Alarm Dashboard**: Real-time view of intercepted threats (both PII leaks and Toxicity violations) routed by the Diff Engine.

### 3.2. Threat Detection & Routing (Backend)
* **Diff Engine (`diff_engine.py`)**: Asynchronously monitors the payload delta (Raw vs. Masked). If a mutation occurs, it routes an alarm to `alarms.json` and logs the event in `governance_audit.json`.
* **NLP Caching (`api.py`)**: To ensure the system remains highly performant, the heavy SpaCy/Presidio engine is cached globally. When a rule is toggled in the UI, the engine hot-reloads in milliseconds without dropping the server.

### 3.3. Deterministic & Algorithmic Scanners
* Built-in Presidio Recognizers (Email, Phone, Person).
* Custom Regex Recognizers (Credit Cards, API Keys, Private Keys).
* Algorithmic Recognizers: Python-based verifiers (e.g., `AadhaarRecognizer`) that use checksum math to eliminate false positives.

## User Review Required

> [!IMPORTANT]
> The foundational Governance Sandbox is now complete and fully operational. Please review this document to ensure it accurately reflects your vision for the system. 

## Open Questions for Future Scaling

While the core system is complete, here are some strategic questions for the next phase of development:

1. **Authentication & RBAC**: Currently, the dashboard has a simple hardcoded admin login. Should we integrate OAuth or Role-Based Access Control (RBAC) to allow different teams (e.g., Legal vs. Engineering) specific permissions?
2. **External LLM Support**: The system currently routes to Local Ollama models. Do you want to build an outbound connector to support external APIs like OpenAI (GPT-4) or Anthropic (Claude) through the same shield?
3. **Automated Alerting**: Should the Diff Engine be extended to send Email or Slack/Teams webhooks when a `CRITICAL` severity alarm (like an API Key leak) is intercepted?
4. **Database Migration**: The rules and alarms are currently stored in local JSON files (`pii_rules.json`, `alarms.json`). Should we migrate this state to a production database like PostgreSQL or MongoDB?
