// API wrapper for the FastAPI backend, since in development stages

export const API_BASE = "/api";

let csrfToken = "";

export function setCsrfToken(value = "") {
  csrfToken = value;
}

export async function apiFetch(path, options = {}) {
  const { skipAuthFailureEvent = false, ...fetchOptions } = options;
  const method = (fetchOptions.method || "GET").toUpperCase();
  const headers = new Headers(fetchOptions.headers || {});
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...fetchOptions,
    headers,
    credentials: "include",
  });
  if (res.status === 401 && !skipAuthFailureEvent) {
    window.dispatchEvent(new CustomEvent("examscan:unauthorized"));
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  return res;
}
