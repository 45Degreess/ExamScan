import { apiFetch } from "./client.js";

export async function listBooklets(sessionCode) {
  const res = await apiFetch(`/sessions/${encodeURIComponent(sessionCode)}/booklets`);
  return res.json();
}

export async function collectRuns(sessionCode) {
  const res = await apiFetch(`/sessions/${encodeURIComponent(sessionCode)}/collect-runs`, {
    method: "POST",
  });
  return res.json();
}

export async function captureRun(sessionCode, pages = null) {
  const body = new FormData();
  if (pages != null) body.append("pages", String(pages));
  const res = await apiFetch(`/sessions/${encodeURIComponent(sessionCode)}/capture-run`, {
    method: "POST",
    body,
  });
  return res.json();
}

export async function deleteBooklet(sessionCode, bookletId) {
  const res = await apiFetch(
    `/sessions/${encodeURIComponent(sessionCode)}/booklets/${bookletId}`,
    { method: "DELETE" },
  );
  return res.json();
}
