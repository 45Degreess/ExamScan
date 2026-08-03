import { useState, useEffect } from "react";
import { palette, font, grainUrl, Btn, Label } from "./theme.jsx";
import PdfDemo from "./PdfDemo";

const API_BASE = "/api";

/* Runs API can return either an array of id strings or an array of objects. */
function runIdOf(run) {
  if (typeof run === "string" || typeof run === "number") return String(run);
  return String(run.id ?? run.run_id ?? run.runId ?? JSON.stringify(run));
}

export default function ExamscanDemo() {
  const [runs, setRuns] = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [runsError, setRunsError] = useState(null);

  const [downloadId, setDownloadId] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/runs`);
        if (res.ok) setRuns(await res.json());
      } catch {
        /* ignore — no persisted runs yet */
      }
    })();
  }, []);

  const fetchRuns = async () => {
    setLoadingRuns(true);
    setRunsError(null);
    try {
      const res = await fetch(`${API_BASE}/runs`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to fetch runs");
      }
      setRuns(await res.json());
    } catch (e) {
      setRunsError(e.message);
    } finally {
      setLoadingRuns(false);
    }
  };

  const downloadRun = async () => {
    if (!downloadId.trim()) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${encodeURIComponent(downloadId.trim())}/archive`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to download archive");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `run_${downloadId.trim()}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setDownloadError(e.message);
    } finally {
      setDownloading(false);
    }
  };

  const cardStyle = {
    width: "100%",
    maxWidth: 720,
    background: palette.surface,
    border: `1px solid ${palette.border}`,
    borderRadius: 16,
    overflow: "hidden",
    padding: 24,
    marginBottom: 32,
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: palette.bg,
      backgroundImage: grainUrl,
      backgroundSize: "200px 200px",
      fontFamily: font.body,
      color: palette.text,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      padding: "40px 20px",
    }}>
      <header style={{ textAlign: "center", marginBottom: 48 }}>
        <h1 style={{
          fontFamily: font.display,
          fontSize: 32,
          fontWeight: 400,
          letterSpacing: "0.02em",
          margin: 0,
        }}>Examscan Demo</h1>
        <p style={{
          color: palette.textMuted,
          fontSize: 12,
          letterSpacing: "0.15em",
          textTransform: "uppercase",
          margin: "8px 0 0",
        }}>Pipeline, remote runs, and archive downloads</p>
      </header>

      {/* Section 1: full PDF pipeline, reusing the existing PdfDemo tab */}
      <PdfDemo />

      {/* Section 2: fetch + store run ids */}
      <div style={cardStyle}>
        <Label>Remote Runs</Label>
        <p style={{ fontSize: 12, color: palette.textMuted, marginTop: 0 }}>
          Fetch the current run ids from the remote runs API and store them on the server.
        </p>
        <Btn primary disabled={loadingRuns} onClick={fetchRuns}>
          {loadingRuns ? "⏳ Fetching…" : "⬇ Fetch Runs"}
        </Btn>

        {runs.length > 0 && (
          <div style={{
            marginTop: 20,
            border: `1px solid ${palette.border}`,
            borderRadius: 10,
            padding: 16,
            fontSize: 13,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}>
            {runs.map((run, i) => (
              <div key={i}>{runIdOf(run)}</div>
            ))}
          </div>
        )}

        {runsError && (
          <div style={{
            marginTop: 16,
            padding: "12px 16px",
            background: palette.dangerBg,
            border: `1px solid ${palette.danger}`,
            borderRadius: 8,
            fontSize: 13,
            color: palette.danger,
          }}>
            ⚠ {runsError}
          </div>
        )}
      </div>

      {/* Section 3: download a specific run's raw archive */}
      <div style={cardStyle}>
        <Label>Download Run Archive</Label>
        <p style={{ fontSize: 12, color: palette.textMuted, marginTop: 0 }}>
          Download the raw ZIP archive for a run id, with no processing.
        </p>
        <div style={{ display: "flex", gap: 10 }}>
          <input
            type="text"
            value={downloadId}
            onChange={(e) => setDownloadId(e.target.value)}
            placeholder="run id"
            list="examscan-demo-run-ids"
            style={{
              flex: 1,
              padding: "10px 12px",
              borderRadius: 8,
              border: `1px solid ${palette.border}`,
              background: palette.bg,
              color: palette.text,
              fontFamily: font.body,
              fontSize: 13,
            }}
          />
          <datalist id="examscan-demo-run-ids">
            {runs.map((run, i) => <option key={i} value={runIdOf(run)} />)}
          </datalist>
          <Btn primary disabled={downloading || !downloadId.trim()} onClick={downloadRun}>
            {downloading ? "⏳ Downloading…" : "📦 Download Archive"}
          </Btn>
        </div>

        {downloadError && (
          <div style={{
            marginTop: 16,
            padding: "12px 16px",
            background: palette.dangerBg,
            border: `1px solid ${palette.danger}`,
            borderRadius: 8,
            fontSize: 13,
            color: palette.danger,
          }}>
            ⚠ {downloadError}
          </div>
        )}
      </div>
    </div>
  );
}
