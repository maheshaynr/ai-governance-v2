# Configuration settings for the AI Governance Backend

# The endpoint for your local Ollama instance
OLLAMA_URL = "http://localhost:11434/api/chat"

# The default model to use for all local LLM tasks (Watchdog, Chat, Regex Sandbox)
# Examples: "phi4-mini:3.8b", "llama3.1:latest", "llama3.1:latest", "gemma4:latest'"
DEFAULT_LLM_MODEL = "phi4-mini:3.8b"


# The small, less filtered model used specifically to test the Toxicity Guardrail
TOXIC_LLM_MODEL = "tinyllama:latest"

# The coding model used to suggest Python Regex fixes
CODING_LLM_MODEL = "phi4-mini:3.8b"
