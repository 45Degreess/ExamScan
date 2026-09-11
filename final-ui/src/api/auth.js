import { apiFetch } from "./client.js";

async function jsonRequest(path, method, body, options = {}) {
  const res = await apiFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
    ...options,
  });
  return res.json();
}

export function login(uctId, password) {
  return jsonRequest(
    "/auth/login",
    "POST",
    { uct_id: uctId, password },
    { skipAuthFailureEvent: true },
  );
}

export function requestPassword(uctId) {
  return jsonRequest("/auth/password/request", "POST", { uct_id: uctId });
}

export async function getCurrentUser() {
  const res = await apiFetch("/auth/me", { skipAuthFailureEvent: true });
  return res.json();
}

export function logout() {
  return jsonRequest("/auth/logout", "POST");
}

export async function listStaff() {
  const res = await apiFetch("/admin/users");
  return res.json();
}

export function createStaff(payload) {
  return jsonRequest("/admin/users", "POST", payload);
}

export function updateStaff(userId, payload) {
  return jsonRequest(`/admin/users/${encodeURIComponent(userId)}`, "PATCH", payload);
}

export function emailStaffPassword(userId) {
  return jsonRequest(`/admin/users/${encodeURIComponent(userId)}/password`, "POST");
}
