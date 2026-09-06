// MOCK LOCAL DATA LAYER
// ======================
// The backend (software/routes.py, software/db.py) currently has no way to:
//   - list previously-created sessions               (needs GET /sessions)
//   - list a session's runs with live status          (needs a run<->session
//     link and a status field entirely absent from the `booklets` table)
//   - edit/persist run metadata after creation        (needs an UPDATE path;
//     db.py only has create_session/get_session/insert_booklet)
//   - report a per-run confidence flag                (no such column exists;
//     the closest thing is booklets.course_code_verified, a single boolean)
//   - bulk-download all completed PDFs for a session  (no endpoint serves
//     booklets.pdf_path over HTTP at all, singly or in bulk)
//
// Every function below is a localStorage-backed stand-in so the UI can be
// operated end-to-end today. Each is cross-referenced to the matching
// section of docs/final-ui-api-requirements.md — when that endpoint is
// built, delete the corresponding function here and swap its call sites
// (in src/pages/*.jsx) over to a real src/api/*.js call.

const SESSIONS_KEY = "examscan.mock.sessions";
const RUNS_KEY_PREFIX = "examscan.mock.runs."; // + sessionId

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

// MOCK: real version needs GET /sessions (see docs — "Login page — View
// Previous Session dropdown").
export function listSessions() {
  return readJson(SESSIONS_KEY, []);
}

export function getSession(sessionId) {
  return listSessions().find((s) => String(s.id) === String(sessionId)) || null;
}

// Called after a REAL POST /sessions succeeds, to remember the session
// locally for the "View Previous Session" dropdown and the View Session page.
export function saveSession(session) {
  const sessions = listSessions().filter((s) => String(s.id) !== String(session.id));
  sessions.push(session);
  writeJson(SESSIONS_KEY, sessions);
  return session;
}

// MOCK: real version needs a run<->session listing endpoint (see docs —
// "View Session page — Runs table").
export function listRuns(sessionId) {
  return readJson(RUNS_KEY_PREFIX + sessionId, []);
}

function saveRuns(sessionId, runs) {
  writeJson(RUNS_KEY_PREFIX + sessionId, runs);
}

// MOCK: stands in for "Collect New Runs" / "New Single Run" on the View
// Session page and "Create 1 Run" on the Debug page. Real version needs the
// Pi run-capture flow (server.py POST /api/runs, /capture, /auto-scan) wired
// through the FastAPI backend and linked to a session_id (see docs —
// "View Session page — Collect New Runs" and "New Single Run").
export function addMockRun(sessionId) {
  const runs = listRuns(sessionId);
  const runId = `RUN-${String(runs.length + 1).padStart(3, "0")}`;
  const run = {
    id: runId,
    status: "not_started", // not_started | processing | complete
    confidence: "green", // green | red
    emplid: "",
    courseCode: "",
    pageCount: "",
    pdfUrl: null,
  };
  const updated = [...runs, run];
  saveRuns(sessionId, updated);
  return run;
}

// MOCK: real version needs an UPDATE path for a booklet's metadata (see docs
// — "View Session page — Edit Run"). db.py currently has no update_booklet().
export function updateRun(sessionId, runId, patch) {
  const runs = listRuns(sessionId).map((r) => (r.id === runId ? { ...r, ...patch } : r));
  saveRuns(sessionId, runs);
  return runs.find((r) => r.id === runId);
}
