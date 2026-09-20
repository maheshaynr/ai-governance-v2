// Reads the backend port from frontend/.env (VITE_API_BASE), falling back to 8000 if
// that file is missing. The backend's own port lives in start_backend.bat's --port flag
// -- when you change one, change the other. A restart of `npm run dev` is required after
// editing .env (unlike a source file, Vite only reads env files at server startup).
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const STORAGE_KEY = 'gov_api_key';

// Every endpoint except /system_status (and the deliberately-open external-facing ones,
// see auth.py) now requires an X-API-Key header again. The key is entered once at the
// login gate in App.jsx and kept here for every request this tab makes -- localStorage
// so a refresh doesn't force logging in again.
let currentApiKey = '';
try {
  currentApiKey = localStorage.getItem(STORAGE_KEY) || '';
} catch {
  // Private browsing / storage disabled -- fall back to in-memory only for this tab.
}

export function setApiKey(key) {
  currentApiKey = key || '';
  try {
    if (currentApiKey) localStorage.setItem(STORAGE_KEY, currentApiKey);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore -- the in-memory copy still works for this tab.
  }
}

export function getApiKey() {
  return currentApiKey;
}

export function clearApiKey() {
  setApiKey('');
}

/** Thrown when the server rejects the current key (missing, unknown, or wrong role). */
export class AuthError extends Error {
  constructor(status, detail) {
    super(detail || 'Authentication failed');
    this.name = 'AuthError';
    this.status = status;
  }
}

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (currentApiKey) headers['X-API-Key'] = currentApiKey;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401 || res.status === 403) {
    let detail = res.status === 401 ? 'Invalid or missing API key.' : 'Not permitted.';
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // Non-JSON error body -- keep the default message.
    }
    throw new AuthError(res.status, detail);
  }

  return res.json();
}

function postJson(path, body) {
  return apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function fetchSystemStatus() {
  // Deliberately open (see auth.py) so health checks and the login screen itself work
  // without a key -- calls apiFetch anyway so a key present in localStorage still gets
  // sent, but a missing/invalid one here should not raise a screen-wide AuthError.
  try {
    return await apiFetch('/system_status');
  } catch (e) {
    return { status: 'loading' };
  }
}

export async function fetchWhoAmI() {
  return apiFetch('/whoami');
}

export async function fetchRules() {
  return apiFetch('/rules');
}

export async function fetchTestCases() {
  return apiFetch('/test_cases');
}

export async function addRule(rule) {
  return postJson('/add_rule', rule);
}

export async function updateRule(ruleData) {
  return postJson('/update_rule', ruleData);
}

export async function deleteRule(name) {
  return postJson('/delete_rule', { name });
}

export async function fetchAlarms() {
  return apiFetch('/alarms');
}

export async function deleteAlarm(alarm_id, status = 'DISMISSED') {
  return postJson('/delete_alarm', { alarm_id, status });
}

export async function fetchAnalytics(timeframe = '24h') {
  return apiFetch(`/analytics?timeframe=${timeframe}`);
}

export async function toggleWatchdog(enable_llm_watchdog) {
  return postJson('/toggle_watchdog', { enable_llm_watchdog });
}

export async function toggleCategory(category, enabled) {
  return postJson('/toggle_category', { category, enabled });
}

export async function fetchSubscribers() {
  return apiFetch('/subscribers');
}

export async function addSubscriber(subscriber) {
  return postJson('/add_subscriber', subscriber);
}

export async function updateSubscriber(subscriber) {
  return postJson('/update_subscriber', subscriber);
}

export async function deleteSubscriber(user_name) {
  return postJson('/delete_subscriber', { user_name });
}

export async function queryDb(customerId) {
  return postJson('/query_db', { customer_id: customerId });
}

export async function governAi(text) {
  return postJson('/govern_ai', { text });
}

export async function chatAgent(message, purpose = '') {
  // purpose opts every /chat call into the Consent Gate (see tool_broker.py) -- an
  // empty string is a real, checkable value ("nothing declared"), not the same as
  // omitting the field.
  return postJson('/chat', { message, purpose });
}

export async function demoChat(message, mode, purpose = '') {
  return postJson('/demo_chat', { message, mode, purpose });
}

export async function sandboxSuggestRule(context_snippet, missed_entity_type, value_preview) {
  return postJson('/sandbox_suggest_rule', { context_snippet, missed_entity_type, value_preview });
}

export async function sandboxTestRule(context_snippet, regex_pattern, entity_name) {
  return postJson('/sandbox_test_rule', { context_snippet, regex_pattern, entity_name });
}

export async function toggleToxicity(enable_toxicity_guard) {
  return postJson('/toggle_toxicity', { enable_toxicity_guard });
}

export async function fetchToxicitySettings() {
  return apiFetch('/toxicity_settings');
}

export async function fetchBenchmarks() {
  return apiFetch('/get_benchmarks');
}

// Generic validation for external systems: send raw text, get back a CLEAR / PARTIAL /
// BLOCKED verdict plus the resulting message. Unlike demoChat/chatAgent, this never
// calls the LLM -- it only runs the toxicity and PII/financial/health checks directly.
export async function guardrailValidate(text) {
  return postJson('/guardrail_validate', { text });
}

// Recent /guardrail_validate calls (timestamp, flag, hash -- never the message itself,
// see api.py's _GUARDRAIL_ACTIVITY) -- confirms a call from an external system actually
// arrived, without exposing what it said.
export async function fetchGuardrailActivity() {
  return apiFetch('/guardrail_activity');
}

export async function fetchConsents() {
  return apiFetch('/consents');
}

export async function withdrawConsent(customer_id, data_category, purpose) {
  return postJson('/withdraw_consent', { customer_id, data_category, purpose });
}

// --- Agent Governance Layer -- read-only from the admin UI. Registration/decisions/activity
// are called by external agents (e.g. VOXA) directly, not from this frontend.
export async function fetchAgents() {
  return apiFetch('/v1/agent/agents');
}

export async function revokeAgent(agentId) {
  return apiFetch(`/v1/agent/agents/${agentId}/revoke`, { method: 'POST' });
}

export async function fetchAgentActivity() {
  return apiFetch('/v1/agent/activity');
}

export async function fetchGovernanceEvents() {
  return apiFetch('/v1/agent/events');
}

export async function fetchGovernanceStats() {
  return apiFetch('/v1/agent/stats');
}

export async function updateToxicitySettings({ thresholds, enable_toxicity_guard }) {
  // Takes the request body shape directly -- the caller already builds
  // { thresholds, enable_toxicity_guard }, and wrapping it again here used to nest it
  // one level too deep (body: { thresholds: { thresholds, enable_toxicity_guard } }),
  // which the backend's UpdateToxicitySettingsRequest could not have matched.
  return postJson('/update_toxicity_settings', { thresholds, enable_toxicity_guard });
}
