import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { palette, space, font, radius } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import StatusDot from "../components/StatusDot.jsx";
import DataTable from "../components/DataTable.jsx";
import CameraFeed from "../components/CameraFeed.jsx";
import FormField, { TextInput } from "../components/FormField.jsx";
import { useSession } from "../context/SessionContext.jsx";
import { listRuns, addMockRun, updateRun } from "../api/mockRuns.js";

const STATUS_DOT = { complete: "green", processing: "yellow", not_started: "red" };
const STATUS_LABEL = { complete: "Complete", processing: "Processing", not_started: "Not started" };

export default function ViewSessionPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { currentSession, loadSession } = useSession();
  const [runs, setRuns] = useState([]);
  const [editingRunId, setEditingRunId] = useState(null);
  const [editForm, setEditForm] = useState(null);

  useEffect(() => {
    if (!currentSession || String(currentSession.id) !== String(sessionId)) {
      const loaded = loadSession(sessionId);
      if (!loaded) {
        navigate("/");
        return;
      }
    }
    setRuns(listRuns(sessionId));
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshRuns = () => setRuns(listRuns(sessionId));

  // MOCK: "Collect New Runs" should pull run archives from the Pi via the
  // existing GET/POST /runs proxy (software/routes.py:504-556) and turn each
  // into a session-scoped run row. No such linkage exists yet — see
  // docs/final-ui-api-requirements.md ("View Session page — Collect New Runs").
  const handleCollectRuns = () => {
    addMockRun(sessionId);
    refreshRuns();
  };

  // MOCK: "New Single Run" should trigger the Pi's real capture workflow
  // (server.py POST /api/runs + /capture + /complete) for one run. See docs
  // ("View Session page — New Single Run").
  const handleNewRun = () => {
    addMockRun(sessionId);
    refreshRuns();
  };

  // MOCK: no bulk-download endpoint exists (booklets.pdf_path is never
  // served over HTTP, singly or in bulk). See docs
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

  // MOCK: persists to localStorage only. Real version needs an UPDATE path
  // on the backend (db.py has no update_booklet()) — see docs
  // ("View Session page — Edit Run").
  const saveEdit = () => {
    updateRun(sessionId, editingRunId, editForm);
    refreshRuns();
    cancelEdit();
  };

  if (!currentSession) return null;

  const columns = [
    { key: "id", header: "Run ID" },
    {
      key: "status",
      header: "Completion Status",
      render: (row) => <StatusDot status={STATUS_DOT[row.status]} label={STATUS_LABEL[row.status]} />,
    },
    {
      key: "view",
      header: "View",
      render: (row) => {
        const canView = row.status === "complete" || row.confidence === "red";
        return (
          <a
            href={row.pdfUrl || "#"}
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
                <Button onClick={handleCollectRuns}>Collect New Runs</Button>
                <Button onClick={handleNewRun}>New Single Run</Button>
                <Button onClick={handleDownloadAll}>Download All PDFs</Button>
              </div>
            )}
          </Card>
        </div>

        {/* Right column: runs table, ~half the page */}
        <Card style={{ flex: 1.4, minWidth: 380 }} title="Runs">
          <DataTable columns={columns} rows={runs} emptyText="No runs collected yet." />
        </Card>
      </div>
    </div>
  );
}
