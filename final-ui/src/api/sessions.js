import { apiFetch, API_BASE } from "./client.js";

// GET /health — real endpoint (software/routes.py), used for the
// backend connection dot on the Login page.
export async function checkBackendHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// GET /pi/health — real endpoint (software/routes.py). Server-side proxy to
// the Pi hardware server's GET /api/health, so the browser gets a same-origin
// answer. Returns { ok, streaming, ... } when the Pi is up, { ok: false } when
// it isn't. Used for the Login page's Pi connection dot.
export async function checkPiHealth() {
  try {
    const res = await fetch(`${API_BASE}/pi/health`);
    if (!res.ok) return false;
    const data = await res.json().catch(() => ({}));
    return data.ok === true;
  } catch {
    return false;
  }
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

// Backend scan_sessions row (snake_case) -> the camelCase shape the app's
// `currentSession` uses. `student_count` becomes the `hasRoster` gate for the
// "Edit class list" button (the uploaded filename it replaced was UI-only).
function toSession(row) {
  return {
    id: row.id,
    sessionCode: row.session_code,
    operatorName: row.operator_name,
    courseCode: row.course_code,
    date: row.test_date,
    status: row.status,
    createdAt: row.created_at,
    hasRoster: (row.student_count ?? 0) > 0,
  };
}

// GET /sessions — real endpoint (software/routes.py). Every session, newest
// first, for the Login page's "View Previous Session" picker.
export async function listSessions() {
  const res = await apiFetch("/sessions");
  const { sessions } = await res.json();
  return sessions.map(toSession);
}

// GET /sessions/{id} — real endpoint (software/routes.py). Fetch one session
// by numeric id; used by SessionContext.loadSession to rehydrate on a hard
// refresh of /sessions/:id. Throws on 404.
export async function getSession(sessionId) {
  const res = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}`);
  return toSession(await res.json());
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

// GET /sessions/{code}/archive — real endpoint (software/routes.py). A ZIP of
// every completed booklet's PDF for the session. Point window.open at it (a
// browser download), not apiFetch. 404 when there are no completed booklets.
export function sessionArchiveUrl(sessionCode) {
  return `${API_BASE}/sessions/${encodeURIComponent(sessionCode)}/archive`;
}

// PATCH /sessions/{code}/booklets/{id} — real endpoint (software/routes.py).
// Operator edit of a booklet's OCR fields; only the passed keys change.
// Changing emplid re-links the class-list roster; changing the course code
// recomputes course_code_verified. Returns the updated
// { emplid, course_code_scanned, num_pages, course_code_verified, student_id }.
// Throws on 409 (emplid already used in this session) or 404.
export async function updateBooklet(sessionCode, bookletId, { emplid, courseCodeScanned, numPages }) {
  const fd = new FormData();
  if (emplid != null) fd.append("emplid", emplid);
  if (courseCodeScanned != null) fd.append("course_code_scanned", courseCodeScanned);
  if (numPages != null && numPages !== "") fd.append("num_pages", String(numPages));
  const res = await apiFetch(
    `/sessions/${encodeURIComponent(sessionCode)}/booklets/${encodeURIComponent(bookletId)}`,
    { method: "PATCH", body: fd },
  );
  return res.json();
}

// GET /pi/stream — real endpoint (software/routes.py). Server-side passthrough
// of the Pi hardware server's MJPEG feed. Point an <img> at this (not via
// apiFetch); the browser renders multipart/x-mixed-replace natively.
export function piStreamUrl() {
  return `${API_BASE}/pi/stream`;
}

// POST /detect-preview — real endpoint (software/routes.py). Used by the Debug
// page's "Outline Page Frame Only" button, which is a genuine existing backend
// capability so it is wired for real rather than mocked.
export async function detectPreview(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiFetch("/detect-preview", { method: "POST", body: fd });
  return res.blob();
}

// POST /extract-cover — real endpoint (software/routes.py). Scans a cover
// photo and OCRs the cover-field regions. Returns
// { fields: {name: string}, crops: {name: base64 PNG, no data-URI prefix},
//   confidences: {name: 0-1, Emplid_digits: number[]},
//   scan_dimensions: {width, height}, regions_used: {name: [x,y,w,h]} }.
// Used by the Debug page's "Scan Front Cover Only" button.
export async function extractCover(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiFetch("/extract-cover", { method: "POST", body: fd });
  return res.json();
}

// POST /pi/debug-run — real endpoint (software/routes.py). Server-side proxy
// that creates one run on the Pi hardware server, captures a single page, and
// completes it. Returns { run_id, status, page_count, errors }. Throws with a
// readable message on 502 (Pi unreachable) or 409 (hardware busy). Used by the
// Debug page's "Create 1 Run" button. No database involvement.
export async function createDebugRun() {
  const res = await apiFetch("/pi/debug-run", { method: "POST" });
  return res.json();
}
