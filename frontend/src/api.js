const API_BASE = 'http://localhost:8000';

export async function fetchRules() {
  const res = await fetch(`${API_BASE}/rules`);
  return res.json();
}

export async function fetchTestCases() {
  const res = await fetch(`${API_BASE}/test_cases`);
  return res.json();
}

export async function addRule(rule) {
  const res = await fetch(`${API_BASE}/add_rule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(rule)
  });
  return res.json();
}

export async function updateRule(rule) {
  const res = await fetch(`${API_BASE}/update_rule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(rule)
  });
  return res.json();
}

export async function queryDb(customerId) {
  const res = await fetch(`${API_BASE}/query_db`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customer_id: customerId })
  });
  return res.json();
}

export async function governAi(text) {
  const res = await fetch(`${API_BASE}/govern_ai`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
  });
  return res.json();
}

export async function chatAgent(message) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  });
  return res.json();
}

