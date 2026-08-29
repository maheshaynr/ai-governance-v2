import json
import os

# Configuration settings for the AI Governance Backend.
#
# Values come from config.json (next to this file, or wherever APP_CONFIG_FILE
# points to), so switching machines -- e.g. moving Ollama from a CPU-only box
# to a GPU one -- is just editing that file's model names, no code changes or
# rebuild required. An environment variable with the same name always wins
# over the file, for quick one-off overrides (e.g. `docker run -e ...`).
# If config.json is missing or unreadable, the hardcoded defaults below apply,
# so the app still starts with today's known-good CPU settings.

_DEFAULTS = {
    "OLLAMA_URL": "http://localhost:11434/api/chat",
    "DEFAULT_LLM_MODEL": "phi4-mini-cpu",   # GPU alternative: "phi4-mini:3.8b"
    "TOXIC_LLM_MODEL": "tinyllama-cpu",     # GPU alternative: "tinyllama:latest"
    "CODING_LLM_MODEL": "phi4-mini-cpu",    # GPU alternative: "phi4-mini:3.8b"
}

_CONFIG_FILE = os.environ.get(
    "APP_CONFIG_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
)


def _load_settings():
    settings = dict(_DEFAULTS)

    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            file_settings = json.load(f)
        settings.update({k: v for k, v in file_settings.items() if k in _DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    for key in _DEFAULTS:
        if key in os.environ:
            settings[key] = os.environ[key]

    return settings


_settings = _load_settings()

OLLAMA_URL = _settings["OLLAMA_URL"]
DEFAULT_LLM_MODEL = _settings["DEFAULT_LLM_MODEL"]
TOXIC_LLM_MODEL = _settings["TOXIC_LLM_MODEL"]
CODING_LLM_MODEL = _settings["CODING_LLM_MODEL"]
