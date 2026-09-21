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

    # --- Access control ---
    # Roles are self-declared (X-Role header, see auth.py) -- there is no credential and
    # no per-user identity, so entitlements are keyed by role directly rather than by an
    # individual name. Which database records each role may read through a tool call.
    # "*" means any record; caller is deliberately limited to 101 so the refusal path
    # can be demonstrated without editing config.
    "ENTITLEMENTS": {
        "super_admin": ["*"],
        "admin_pii": ["*"],
        "caller": ["101"],
    },

    # When false, unmasked model output is never returned to any caller. Turning this on
    # additionally requires an admin role -- see api.py's raw output gating.
    "EXPOSE_RAW_OUTPUT": False,

    # --- DPDP Engine (external consent/notice decision service) ---
    # Empty DPDP_BASE_URL is the fail-closed default -- dpdp_client.py refuses to even
    # attempt a call and returns guard_failed=True immediately rather than requesting
    # against "". Real values belong in config.json or the environment, never source.
    "DPDP_BASE_URL": "",
    "DPDP_SERVICE_TOKEN": "",
    "DPDP_TENANT_ID": "jio",
    "DPDP_TIMEOUT_SECONDS": 3,
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

    for key, default in _DEFAULTS.items():
        if key not in os.environ:
            continue

        raw = os.environ[key]
        if isinstance(default, str):
            settings[key] = raw
            continue

        # Non-string settings (the key map, entitlements, booleans) arrive from the
        # environment as JSON. A malformed value falls back to the file/default value
        # rather than crashing startup -- but it is loud, because silently running with
        # the wrong access-control config is worse than a noisy log line.
        try:
            settings[key] = json.loads(raw)
        except json.JSONDecodeError:
            print(f"config: ignoring {key} from environment -- not valid JSON")

    return settings


_settings = _load_settings()

OLLAMA_URL = _settings["OLLAMA_URL"]
DEFAULT_LLM_MODEL = _settings["DEFAULT_LLM_MODEL"]
TOXIC_LLM_MODEL = _settings["TOXIC_LLM_MODEL"]
CODING_LLM_MODEL = _settings["CODING_LLM_MODEL"]
ENTITLEMENTS = _settings["ENTITLEMENTS"]
EXPOSE_RAW_OUTPUT = _settings["EXPOSE_RAW_OUTPUT"]
DPDP_BASE_URL = _settings["DPDP_BASE_URL"]
DPDP_SERVICE_TOKEN = _settings["DPDP_SERVICE_TOKEN"]
DPDP_TENANT_ID = _settings["DPDP_TENANT_ID"]
DPDP_TIMEOUT_SECONDS = _settings["DPDP_TIMEOUT_SECONDS"]
