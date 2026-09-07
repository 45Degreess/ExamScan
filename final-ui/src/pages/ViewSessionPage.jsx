import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { palette, space, font, radius } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import StatusDot from "../components/StatusDot.jsx";
import DataTable from "../components/DataTable.jsx";
import CameraFeed from "../components/CameraFeed.jsx";
import FormField, { TextInput } from "../components/FormField.jsx";
import { useSession } from "../context/SessionContext.jsx";
import { collectRuns, listBooklets } from "../api/runs.js";
import { bookletPdfUrl } from "../api/sessions.js";
import { updateRun } from "../api/mockRuns.js";

const POLL_MS = 4000;

const STATUS_DOT = { complete: "green", processing: "yellow", error: "red" };
const STATUS_LABEL = { complete: "Complete", processing: "Processing", error: "Error" };

// Backend booklet (software/routes.py GET /sessions/{code}/booklets) -> table row.
function toRow(b) {
  const lowConfidence =
    b.confidence == null || b.confidence < 0.5 || b.course_code_verified === false;
  return {
    id: b.run_id || `#${b.id}`,
    bookletId: b.id,
    status: b.status,
    errorMessage: b.error_message,
    confidence: lowConfidence ? "red" : "green",
    emplid: b.emplid || "",
    courseCode: b.course_code_scanned || "",
    pageCount: b.num_pages ?? "",
  };
}

export default function ViewSessionPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { currentSession, loadSession } = useSession();
  const [runs, setRuns] = useState([]);
  const [editingRunId, setEditingRunId] = useState(null);
  const [editForm, setEditForm] = useState(null);
  const [collecting, setCollecting] = useState(false);
  const [notice, setNotice] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const sessionCodeRef = useRef(null);

  useEffect(() => {
    let session = currentSession;
    if (!session || String(session.id) !== String(sessionId)) {
      session = loadSession(sessionId);
      if (!session) {
        navigate("/");
        return;
      }
    }
    const sessionCode = session.sessionCode;
    sessionCodeRef.current = sessionCode;

    let cancelled = false;
    const poll = async () => {
      try {
        const data = await listBooklets(sessionCode);
        if (cancelled) return;
        setRuns((data.booklets || []).map(toRow));
        setLoadError(null);
      } catch (e) {
        if (!cancelled) setLoadError(e.message); // keep the last good rows
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshRuns = async () => {
    const sessionCode = sessionCodeRef.current;
    if (!sessionCode) return;
    try {
      const data = await listBooklets(sessionCode);
      setRuns((data.booklets || []).map(toRow));
      setLoadError(null);
    } catch (e) {
      setLoadError(e.message);
    }
  };

  // Pull every completed Pi run not yet collected for this session; the poll
  // above then surfaces the new rows as they move processing -> complete.
  const handleCollectRuns = async () => {
    const sessionCode = sessionCodeRef.current;
    if (!sessionCode || collecting) return;
    setCollecting(true);
    setNotice(null);
    try {
      const res = await collectRuns(sessionCode);
      const n = res.queued?.length ?? 0;
      setNotice(
        n > 0
          ? `Queued ${n} run${n === 1 ? "" : "s"} for processing…`
          : "No new completed runs on the Pi.",
      );
      refreshRuns();
    } catch (e) {
      setNotice(e.message);
    } finally {
      setCollecting(false);
    }
  };

  // MOCK: "New Single Run" should trigger the Pi's real capture workflow
  // (server.py POST /api/runs + /capture + /complete) for one run. See
  // docs/final-ui-api-requirements.md ("View Session page — New Single Run").
  const handleNewRun = () => {
    setNotice("New Single Run isn't wired to the Pi yet — see docs/final-ui-api-requirements.md.");
  };

  // MOCK: no bulk-download endpoint exists yet. See docs
  // ("View Session page — Download All PDFs").
  const handleDownloadAll = () => {
    alert("Not yet implemented — the backend has no endpoint to download completed PDFs. See docs/final-ui-api-requirements.md.");
  };

  const openEdit = (run) => {
    setEditingRunId(run.id);
    setEditForm({ emplid: run.emplid || "", courseCode: run.courseCode || "", pageCount: run.pageCount || "" });
  };

  const cancelEdit = () => {
    setEditingRunId(null);
    setEditForm(null);
  };

  // MOCK: writes to localStorage only and will be overwritten by the next poll.
  // Real version needs PATCH /sessions/{code}/booklets/{id} (db.py has no
  // update path for operator edits) — see docs ("View Session page — Edit Run").
  const saveEdit = () => {
    updateRun(sessionId, editingRunId, editForm);
    setNotice("Edit saved locally only — booklet metadata editing isn't wired to the backend yet.");
    cancelEdit();
  };

  if (!currentSession) return null;

  const columns = [
    { key: "id", header: "Run ID" },
    {
      key: "status",
      header: "Completion Status",
      render: (row) => (
        <span title={row.status === "error" ? row.errorMessage || "" : undefined}>
          <StatusDot status={STATUS_DOT[row.status] || "red"} label={STATUS_LABEL[row.status] || row.status} />
        </span>
      ),
    },
    {
      key: "view",
      header: "View",
      render: (row) => {
        const canView = row.status === "complete";
        const href = canView ? bookletPdfUrl(sessionCodeRef.current, row.bookletId) : "#";
        return (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => !canView && e.preventDefault()}
            style={{
              color: canView ? palette.primary : palette.neutral,
              pointerEvents: canView ? "auto" : "none",
              fontSize: 13,
              textDecoration: canView ? "underline" : "none",
            }}
            title={canView ? undefined : "Not available yet"}
          >
            View PDF
          </a>
        );
      },
    },
    {
      key: "edit",
      header: "Edit Run",
      render: (row) => (
        <Button variant="subtle" style={{ padding: "4px 10px" }} onClick={() => openEdit(row)}>
          Edit
        </Button>
      ),
    },
    {
      key: "confidence",
      header: "Confidence Flag",
      render: (row) => <StatusDot status={row.confidence === "red" ? "red" : "green"} />,
    },
  ];

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, fontFamily: font.body, color: palette.text, padding: space.lg }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: space.lg }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>{currentSession.sessionCode}</h1>
        <div style={{ display: "flex", gap: space.sm }}>
          <Button variant="primary" onClick={() => navigate(`/sessions/${sessionId}/review`)}>
            Review &amp; finalize
          </Button>
          {currentSession.studentListName && (
            <Button variant="subtle" onClick={() => navigate(`/sessions/${sessionId}/prepare`)}>
              Edit class list
            </Button>
          )}
          <Button variant="subtle" onClick={() => navigate("/")}>← Back to Login</Button>
        </div>
      </div>

      <div style={{ display: "flex", gap: space.lg, alignItems: "stretch" }}>
        {/* Left column: two stacked boxes, evenly spaced */}
        <div style={{ flex: 1, minWidth: 280, display: "flex", flexDirection: "column", gap: space.lg }}>
          {/* Top-left: live MJPEG feed from the Pi, proxied via /api/pi/stream
              (software/routes.py). CameraFeed owns its own reconnect loop. */}
          <Card style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", minHeight: 180, padding: 0, overflow: "hidden" }}>
            <CameraFeed />
          </Card>

          {/* Bottom-left: buttons, toggling to the edit-run form */}
          <Card style={{ flex: 1, minHeight: 180 }}>
            {editingRunId ? (
              <div>
                <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 600 }}>Edit Run {editingRunId}</h3>
                <FormField label="Emplid">
                  <TextInput value={editForm.emplid} onChange={(e) => setEditForm({ ...editForm, emplid: e.target.value })} />
                </FormField>
                <FormField label="Course Code">
                  <TextInput value={editForm.courseCode} onChange={(e) => setEditForm({ ...editForm, courseCode: e.target.value })} />
                </FormField>
                <FormField label="Page Count">
                  <TextInput value={editForm.pageCount} onChange={(e) => setEditForm({ ...editForm, pageCount: e.target.value })} />
                </FormField>
                <div style={{ display: "flex", gap: space.sm, justifyContent: "flex-end" }}>
                  <Button variant="subtle" onClick={cancelEdit}>Cancel</Button>
                  <Button variant="primary" onClick={saveEdit}>Save</Button>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
                <Button onClick={handleCollectRuns} disabled={collecting}>
                  {collecting ? "Collecting…" : "Collect New Runs"}
                </Button>
                <Button onClick={handleNewRun}>New Single Run</Button>
                <Button onClick={handleDownloadAll}>Download All PDFs</Button>
                {notice && (
                  <div style={{ fontSize: 12, color: palette.textMuted, marginTop: space.xs }}>{notice}</div>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* Right column: runs table, ~half the page */}
        <Card style={{ flex: 1.4, minWidth: 380 }} title="Runs">
          {loadError && (
            <div
              style={{
                marginBottom: space.sm,
                padding: "8px 12px",
                background: palette.dangerBg,
                border: `1px solid ${palette.danger}`,
                borderRadius: 8,
                fontSize: 12,
                color: palette.danger,
              }}
            >
              Couldn’t refresh runs: {loadError}
            </div>
          )}
          <DataTable columns={columns} rows={runs} emptyText="No runs collected yet." />
        </Card>
      </div>
    </div>
  );
}
