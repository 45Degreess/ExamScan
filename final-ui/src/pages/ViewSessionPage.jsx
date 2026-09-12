import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { palette, space, font, radius } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import StatusDot from "../components/StatusDot.jsx";
import DataTable from "../components/DataTable.jsx";
import CameraFeed from "../components/CameraFeed.jsx";
import BookletEditForm from "../components/BookletEditForm.jsx";
import { useSession } from "../context/SessionContext.jsx";
import { captureRun, collectRuns, listBooklets } from "../api/runs.js";
import { bookletPdfUrl, sessionArchiveUrl } from "../api/sessions.js";

const POLL_MS = 4000;

const STATUS_DOT = { complete: "green", processing: "yellow", error: "red" };
const STATUS_LABEL = { complete: "Complete", processing: "Processing", error: "Error" };

// Backend booklet (software/routes.py GET /sessions/{code}/booklets) -> table row.
function toRow(b) {
  // Confidence is only meaningful once OCR has run — leave processing/error
  // rows neutral rather than flagging them red before there's a score.
  let confidence = "gray";
  if (b.status === "complete") {
    const low =
      b.confidence == null || b.confidence < 0.5 || b.course_code_verified === false;
    confidence = low ? "red" : "green";
  }
  return {
    id: b.run_id || `#${b.id}`,
    bookletId: b.id,
    status: b.status,
    errorMessage: b.error_message,
    confidence,
    confidenceScore: b.confidence,
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
  const [editBooklet, setEditBooklet] = useState(null);
  const [collecting, setCollecting] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [notice, setNotice] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const sessionCodeRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    (async () => {
      let session = currentSession;
      if (!session || String(session.id) !== String(sessionId)) {
        session = await loadSession(sessionId);
      }
      if (cancelled) return;
      if (!session) {
        navigate("/home");
        return;
      }
      const sessionCode = session.sessionCode;
      sessionCodeRef.current = sessionCode;

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
      timer = setInterval(poll, POLL_MS);
    })();

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
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

  // Trigger a fresh Pi scan for this session (create run + auto-scan). The
  // request blocks for the physical scan; the poll then shows the new row go
  // processing -> complete.
  const handleNewRun = async () => {
    const sessionCode = sessionCodeRef.current;
    if (!sessionCode || capturing || collecting) return;
    setCapturing(true);
    setNotice(null);
    try {
      const res = await captureRun(sessionCode);
      setNotice(`Captured run ${res.run_id} — processing…`);
      refreshRuns();
    } catch (e) {
      setNotice(e.message);
    } finally {
      setCapturing(false);
    }
  };

  // Download a ZIP of every completed booklet's PDF for this session.
  const handleDownloadAll = () => {
    const sessionCode = sessionCodeRef.current;
    if (!sessionCode) return;
    if (!runs.some((r) => r.status === "complete")) {
      setNotice("No completed booklets to download yet.");
      return;
    }
    window.open(sessionArchiveUrl(sessionCode), "_blank", "noopener");
  };

  const openEdit = (row) => {
    setEditBooklet({
      id: row.bookletId,
      emplid: row.emplid,
      courseCodeScanned: row.courseCode,
      numPages: row.pageCount === "" ? null : row.pageCount,
    });
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
      render: (row) =>
        row.status === "complete" ? (
          <Button variant="subtle" style={{ padding: "4px 10px" }} onClick={() => openEdit(row)}>
            Edit
          </Button>
        ) : (
          <span style={{ color: palette.neutral }}>—</span>
        ),
    },
    {
      key: "confidence",
      header: "Confidence Flag",
      render: (row) => (
        <StatusDot
          status={row.confidence}
          label={
            row.confidenceScore != null
              ? `${Math.round(row.confidenceScore * 100)}%`
              : undefined
          }
          title={
            row.confidence === "gray"
              ? "No confidence score until the run finishes processing"
              : row.confidence === "red"
                ? "Low OCR confidence or course-code mismatch — review this booklet"
                : "OCR confidence OK"
          }
        />
      ),
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
          {currentSession.hasRoster && (
            <Button variant="subtle" onClick={() => navigate(`/sessions/${sessionId}/prepare`)}>
              Edit class list
            </Button>
          )}
          <Button variant="subtle" onClick={() => navigate("/home")}>← Back to Login</Button>
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

          {/* Bottom-left: buttons, toggling to the booklet-edit form */}
          <Card style={{ flex: 1, minHeight: 180 }}>
            {editBooklet ? (
              <BookletEditForm
                sessionCode={sessionCodeRef.current}
                booklet={editBooklet}
                onSaved={() => {
                  setEditBooklet(null);
                  setNotice("Booklet updated.");
                  refreshRuns();
                }}
                onCancel={() => setEditBooklet(null)}
              />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
                <Button onClick={handleCollectRuns} disabled={collecting || capturing}>
                  {collecting ? "Collecting…" : "Collect New Runs"}
                </Button>
                <Button onClick={handleNewRun} disabled={collecting || capturing}>
                  {capturing ? "Scanning…" : "New Single Run"}
                </Button>
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
