# AI Governance Proof of Concept: "Inbound Content Shield"

We are building a Dual-LLM architecture that demonstrates how a **Control Layer acts as a protective shield** between frustrated end-users and downstream external systems. 

## User Review Required

> [!IMPORTANT]
> The plan has been updated to reflect a **Decoupled Client-Server Architecture**. The Governance logic will now live entirely on a Backend API, allowing the Frontend UI to be completely swapped out (e.g., for React) in the future. Please review this architectural upgrade.

---

## 1. Architecture Flow & Enterprise Controls (Decoupled)

1.  **Frontend Chat Interface (Client):** A "thin client" UI (Streamlit for this PoC, easily swappable to React later). It contains no governance logic. It simply sends user text via an HTTP POST request to our backend.
2.  **Backend Governance API (Server):** A Python REST API (FastAPI) that centralizes all AI and privacy logic.
3.  **Input Guardrail (Microsoft Presidio):** Runs securely inside the Backend API. It deterministically and contextually masks PII.
4.  **LLM-1 (The Baseline / Failure Comparison):** The raw `TinyLlama` base model. *(Bypassed in final pipeline, used only for comparison).*
5.  **LLM-2 (The Governance Control Layer):** The trained model acts as the "Toxic-to-Polite" translator inside the backend.
6.  **Fidelity Check (Keyword-Coverage v1):** A lightweight backend algorithm verifies LLM-2 didn't drop key facts.
7.  **Fallback Policy:** If the rewrite fails, the backend returns the PII-Masked text with a `[FLAGGED_FOR_TOXICITY]` warning.
8.  **Audit Logging:** The Backend API saves every step to `governance_audit.json` proving a chain of custody.

---

## 2. PoC Test Cases (Success Criteria)

### Test Case 1: Pure PII Leakage
*   **User Input:** "My name is John Smith. Check my account, my SSN is 123-45-6789."
*   **Governed Pipeline Output (Success):** "My name is [PERSON]. Check my account, my SSN is [US_SSN]."

### Test Case 2: Extreme Toxicity (Agent Shielding)
*   **User Input:** "Your internet service is absolute trash! You incompetent idiots need to fix my router right now before I cancel everything!"
*   **Governed Pipeline Output (Success):** "The customer is extremely dissatisfied with their internet service and is threatening to cancel. They are requesting an immediate fix for their router."

### Test Case 3: The Fallback Trigger (Safety Net)
*   **User Input:** "Fix my billing issue you morons!"
*   **Governed Pipeline Output (Success):** `[WARNING: FLAGGED_FOR_TOXICITY] "Fix my billing issue you morons!"`

---

## 3. Execution Strategy
*   **Phase 1 (Decoupled Architecture):** 
    *   Build `api.py` (FastAPI) to host Presidio, the Fidelity Checker, and Audit Logger.
    *   Refactor `app.py` (Streamlit) to be a pure frontend that makes HTTP calls to `api.py`.
*   **Phase 2 (Colab):** Train LLM-2 (TinyLlama) in Google Colab on a synthetic "Toxic -> Polite" dataset.
*   **Phase 3 (Local Integration):** Combine the pipeline and run the Test Cases.
