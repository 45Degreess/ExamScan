// Thin fetch wrapper for the real FastAPI backend (software/scanner_api.py).
// Mirrors examscan-ui's convention: API_BASE = "/api", proxied by vite.config.js.
export const API_BASE = "/api";

export async function apiFetch(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  return res;
}
