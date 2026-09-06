import { apiFetch, API_BASE } from "./client.js";

// GET /health — real endpoint (software/routes.py:215-217), used for the
// backend connection dot on the Login page.
export async function checkBackendHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// MOCK: there is no way to check Raspberry Pi connectivity from the browser
// today. The Pi's hardware server (server.py) exposes GET /api/health on its
// own host/port (config.toml, default 10.42.0.1:8000) with no CORS headers
// and no proxy from the FastAPI backend. See docs/final-ui-api-requirements.md
// ("Login page — Pi connection status") for what's needed to make this real.
export async function checkPiHealth() {
  return false;
}

// POST /sessions — real endpoint (software/routes.py). Returns
// { session_id, session_code, students_imported }. Throws with a readable
// message on 409 (duplicate session_code) or 400 (bad date).
//
// `classListFile` (optional) is the class-list CSV (Name, Pronouns, UserName,
// Email, Role, LastAccessed). The backend keeps only Role=Student rows and
// seeds the session_students roster from them.
export async function createSession({ sessionCode, operatorName, testDate, courseCode, classListFile }) {
  const fd = new FormData();
  fd.append("session_code", sessionCode);
  fd.append("operator_name", operatorName);
  fd.append("test_date", testDate); // expects YYYY-MM-DD
  fd.append("course_code", courseCode);
  if (classListFile) fd.append("class_list", classListFile);
  const res = await apiFetch("/sessions", { method: "POST", body: fd });
  return res.json();
}

// GET /sessions/{code}/students — real endpoint (software/routes.py).
// Returns { session_code, students: [{ id, name, username, role, expected,
// scanned, booklet_id, scanned_at, status }] }.
export async function getSessionStudents(sessionCode) {
  const res = await apiFetch(`/sessions/${encodeURIComponent(sessionCode)}/students`);
  return res.json();
}

// PUT /sessions/{code}/students/expected — real endpoint (software/routes.py).
// `excludedUsernames` is the list of roster usernames to mark NOT expected
// (deselected); everyone else is (re-)marked expected. Returns
// { session_code, expected, excluded }.
export async function setExpectedStudents(sessionCode, excludedUsernames) {
  const fd = new FormData();
  for (const username of excludedUsernames) fd.append("excluded", username);
  const res = await apiFetch(`/sessions/${encodeURIComponent(sessionCode)}/students/expected`, {
    method: "PUT",
    body: fd,
  });
  return res.json();
}

// GET /sessions/{code}/review — real endpoint (software/routes.py). Returns
// { session_code, session_status, items: [{ row_key, kind, student_id,
// booklet_id, name, username, emplid, status, expected, scanned, confidence,
// course_code_scanned, course_code_verified, num_pages, scanned_at }] },
// already sorted unexpected → missing → scanned → excluded.
export async function getSessionReview(sessionCode) {
  const res = await apiFetch(`/sessions/${encodeURIComponent(sessionCode)}/review`);
  return res.json();
}

// POST /sessions/{code}/finalize — real endpoint (software/routes.py).
// Persists the final expected flags (roster usernames in `excludedUsernames`
// → expected=0) AND marks the session finalized, in one request. Advisory
// only (nothing is locked) and idempotent. Returns { session_code, status,
// expected, excluded, scanned, missing, unexpected }.
export async function finalizeSession(sessionCode, excludedUsernames = []) {
  const fd = new FormData();
  for (const username of excludedUsernames) fd.append("excluded", username);
  const res = await apiFetch(`/sessions/${encodeURIComponent(sessionCode)}/finalize`, {
    method: "POST",
    body: fd,
  });
  return res.json();
}

// Direct URL to a booklet's combined PDF (opened in a new tab, not via
// apiFetch). GET /sessions/{code}/booklets/{id}/pdf streams it inline.
export function bookletPdfUrl(sessionCode, bookletId) {
  return `${API_BASE}/sessions/${encodeURIComponent(sessionCode)}/booklets/${encodeURIComponent(bookletId)}/pdf`;
}

// POST /detect-preview — real endpoint (software/routes.py:249-270). Used by
// the Debug page's "Outline Page Frame Only" button, which is a genuine
// existing backend capability so it is wired for real rather than mocked.
export async function detectPreview(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiFetch("/detect-preview", { method: "POST", body: fd });
  return res.blob();
}

// MOCK: there is no backend endpoint for OCR-only-the-front-cover as a
// standalone "quick check" call distinct from /extract-cover's full response
// shape used elsewhere. The Debug page's "Scan Front Cover Only" therefore
// stays fully mocked for now. See docs/final-ui-api-requirements.md
// ("Debug page — Scan Front Cover Only").
