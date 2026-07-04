# AI Governance PoC: Execution Tasks

- [ ] **Phase 1: Local Guardrails (PII)**
  - [ ] Initialize Python environment in the workspace.
  - [ ] Install Presidio dependencies (`presidio-analyzer`, `presidio-anonymizer`, `spacy`).
  - [ ] Write `guardrail_controller.py` to intercept prompts and mask PII (SSN, Email, Phone).
- [ ] **Phase 2: Cloud Training (RMF/Safety)**
  - [ ] Write Google Colab training script (`colab_training_script.py`).
  - [ ] Include code for loading `TinyLlama_v1.1`, applying LoRA config, and loading the Anthropic safety dataset.
  - [ ] Include code to export the model to GGUF format so it can be easily run locally in Ollama later.
- [ ] **Phase 3: Final Integration**
  - [ ] Write the final test script to combine the local guardrail with the locally-hosted trained model.
