import { Fragment, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusDot from "../components/StatusDot.jsx";
import { detectPreview, extractCover, extractMark, extractBooklet, createDebugRun } from "../api/sessions.js";

const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

const BUSY_LABEL = {
  cover: "Scanning cover…",
  outline: "Outlining frame…",
  run: "Capturing run…",
  mark: "Scanning mark regions…",
  booklet: "Testing extraction…",
};

// 0-1 confidence -> coloured dot + percentage. Mirrors confidenceCell in
// ReviewSessionPage.jsx (small helper, kept local).
function confidenceCell(c) {
  if (c === null || c === undefined) return <span style={{ color: palette.textMuted }}>—</span>;
  const pct = Math.round(c * 100);
  const dot = c >= 0.8 ? "green" : c >= 0.5 ? "yellow" : "red";
  return <StatusDot status={dot} label={`${pct}%`} />;
}

// /extract-cover response -> one row per cover field.
function coverRows(data) {
  const { fields = {}, crops = {}, confidences = {}, regions_used = {} } = data || {};
  return Object.keys(fields).map((name) => ({
    id: name,
    field: name,
    crop: crops[name] || null,
    value: fields[name],
    confidence: typeof confidences[name] === "number" ? confidences[name] : null,
    digits:
      name === "Emplid" && Array.isArray(confidences.Emplid_digits)
        ? confidences.Emplid_digits
        : null,
    region: Array.isArray(regions_used[name]) ? regions_used[name] : null,
  }));
}

const coverColumns = [
  { key: "field", header: "Field" },
  {
    key: "crop",
    header: "Crop",
    render: (row) =>
      row.crop ? (
        <img
          src={`data:image/png;base64,${row.crop}`}
          alt={`${row.field} crop`}
          style={{
            maxHeight: 44,
            maxWidth: 360,
            border: `1px solid ${palette.border}`,
            borderRadius: 4,
            imageRendering: "pixelated",
            display: "block",
          }}
        />
      ) : (
        <span style={{ color: palette.textMuted }}>—</span>
      ),
  },
  {
    key: "value",
    header: "OCR value",
    render: (row) => {
      const v = row.value ?? "";
      const bad = !v || v.includes("[OCR error") || v.includes("?");
      return (
        <span style={{ fontFamily: MONO, color: bad ? palette.danger : palette.text }}>
          {v || "—"}
        </span>
      );
    },
  },
  {
    key: "confidence",
    header: "Confidence",
    render: (row) => (
      <div>
        {confidenceCell(row.confidence)}
        {row.digits && (
          <div style={{ fontSize: 11, color: palette.textMuted, marginTop: 2, fontFamily: MONO }}>
            {row.digits.map((d) => Math.round(d * 100)).join(" · ")}
          </div>
        )}
      </div>
    ),
  },
  {
    key: "region",
    header: "Region",
    render: (row) => (
      <span style={{ fontSize: 11, color: palette.textMuted, fontFamily: MONO }}>
        {row.region ? row.region.join(", ") : "—"}
      </span>
    ),
  },
];

// /extract-mark response -> one row per candidate number found.
function markRows(data) {
  const { candidates = [], regions_used: regionsUsed = [] } = data || {};
  return candidates.map((c, i) => ({
    id: i,
    region: regionsUsed[c.region_index] || null,
    regionIndex: c.region_index,
    crop: c.crop || null,
    value: c.value,
    confidence: typeof c.confidence === "number" ? c.confidence : null,
    selected: !!c.selected,
  }));
}

const markColumns = [
  {
    key: "region",
    header: "Box",
    render: (row) => (
      <span style={{ fontSize: 11, color: palette.textMuted, fontFamily: MONO }}>
        #{row.regionIndex + 1}{row.region ? ` (${row.region.join(", ")})` : ""}
      </span>
    ),
  },
  {
    key: "crop",
    header: "Crop",
    render: (row) =>
      row.crop ? (
        <img
          src={`data:image/png;base64,${row.crop}`}
          alt="Candidate crop"
          style={{
            maxHeight: 44,
            maxWidth: 200,
            border: `1px solid ${palette.border}`,
            borderRadius: 4,
            imageRendering: "pixelated",
            display: "block",
          }}
        />
      ) : (
        <span style={{ color: palette.textMuted }}>—</span>
      ),
  },
  {
    key: "value",
    header: "Value",
    render: (row) => (
      <span style={{ fontFamily: MONO, fontWeight: row.selected ? 700 : 400 }}>
        {row.value}
        {row.selected && (
          <span style={{ marginLeft: 6, fontSize: 11, color: palette.primary }}>★ mark</span>
        )}
      </span>
    ),
  },
  {
    key: "confidence",
    header: "Confidence",
    render: (row) => confidenceCell(row.confidence),
  },
];

// /extract-booklet response -> one row per image in the upload.
function bookletImageRows(data) {
  const { images = [] } = data || {};
  return images.map((img, i) => ({
    id: i,
    filename: img.filename,
    qrFound: img.qr_found,
    error: img.error,
  }));
}

const bookletImageColumns = [
  { key: "filename", header: "File" },
  {
    key: "qrFound",
    header: "Cover QR?",
    render: (row) =>
      row.qrFound == null ? (
        <span style={{ color: palette.textMuted }}>—</span>
      ) : (
        <StatusDot status={row.qrFound ? "green" : "gray"} label={row.qrFound ? "yes" : "no"} />
      ),
  },
  {
    key: "error",
    header: "Error",
    render: (row) =>
      row.error ? (
        <span style={{ color: palette.danger, fontSize: 12 }}>{row.error}</span>
      ) : (
        <span style={{ color: palette.textMuted }}>—</span>
      ),
  },
];

export default function DebugPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const pendingActionRef = useRef(null); // "cover" | "outline" | "mark" | "booklet"
  const [result, setResult] = useState({ kind: "idle" });
  const [busy, setBusy] = useState(null); // null | "cover" | "outline" | "run"
  const [error, setError] = useState(null);
  const [applyOverlay, setApplyOverlay] = useState(false);

  const resultRef = useRef(result);
  resultRef.current = result;
  useEffect(
    () => () => {
      if (resultRef.current.kind === "image") URL.revokeObjectURL(resultRef.current.url);
    },
    [],
  );

  const pickImage = (action) => {
    pendingActionRef.current = action;
    fileInputRef.current?.click();
  };

  const onFileSelected = async (e) => {
    const file = e.target.files?.[0];
    const action = pendingActionRef.current;
    if (!file || !action) return;
    if (result.kind === "image") URL.revokeObjectURL(result.url);
    setBusy(action);
    setError(null);
    try {
      if (action === "outline") {
        const blob = await detectPreview(file, applyOverlay);
        setResult({ kind: "image", url: URL.createObjectURL(blob) });
      } else if (action === "mark") {
        const data = await extractMark(file, applyOverlay);
        setResult({ kind: "mark", data });
      } else if (action === "booklet") {
        const data = await extractBooklet(file, applyOverlay);
        setResult({ kind: "booklet", data });
      } else {
        const data = await extractCover(file, applyOverlay);
        setResult({ kind: "cover", data });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
      e.target.value = "";
    }
  };

  const handleCreateRun = async () => {
    if (result.kind === "image") URL.revokeObjectURL(result.url);
    setBusy("run");
    setError(null);
    try {
      const data = await createDebugRun();
      setResult({ kind: "run", data });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  };

  const renderResult = () => {
    if (busy) {
      return <span style={{ color: palette.textMuted, fontSize: 14 }}>{BUSY_LABEL[busy]}</span>;
    }
    if (result.kind === "image") {
      return (
        <img
          src={result.url}
          alt="Detected page frame"
          style={{ maxWidth: "100%", maxHeight: 420, borderRadius: 8 }}
        />
      );
    }
    if (result.kind === "cover") {
      const { scan_dimensions: dims } = result.data || {};
      return (
        <div style={{ width: "100%" }}>
          <DataTable
            columns={coverColumns}
            rows={coverRows(result.data)}
            emptyText="No fields extracted."
            maxHeight={360}
          />
          {dims && (
            <div style={{ marginTop: space.sm, fontSize: 12, color: palette.textMuted }}>
              Scanned at {dims.width}×{dims.height}
            </div>
          )}
        </div>
      );
    }
    if (result.kind === "mark") {
      const { mark, mark_confidence: markConfidence, scan_dimensions: dims } = result.data || {};
      return (
        <div style={{ width: "100%" }}>
          <div style={{ marginBottom: space.sm, fontSize: 13 }}>
            {mark != null ? (
              <>
                Extracted mark: <strong>{mark}</strong> {confidenceCell(markConfidence)}
              </>
            ) : (
              <span style={{ color: palette.textMuted }}>No candidates found.</span>
            )}
          </div>
          <DataTable
            columns={markColumns}
            rows={markRows(result.data)}
            emptyText="No candidates extracted."
            maxHeight={360}
          />
          {dims && (
            <div style={{ marginTop: space.sm, fontSize: 12, color: palette.textMuted }}>
              Scanned at {dims.width}×{dims.height}
            </div>
          )}
        </div>
      );
    }
    if (result.kind === "booklet") {
      const { num_images: numImages, cover_found: coverFound, cover, mark } = result.data || {};
      return (
        <div style={{ width: "100%" }}>
          <div style={{ marginBottom: space.sm, fontSize: 13 }}>
            {numImages} image{numImages === 1 ? "" : "s"} processed —{" "}
            {coverFound ? "cover page found" : (
              <span style={{ color: palette.danger }}>no cover page found</span>
            )}
          </div>
          <DataTable
            columns={bookletImageColumns}
            rows={bookletImageRows(result.data)}
            emptyText="No images."
            maxHeight={160}
          />
          {cover && !cover.error && (
            <>
              <div style={{ margin: `${space.md}px 0 ${space.xs}px`, fontSize: 12, fontWeight: 600 }}>
                Cover fields
              </div>
              <DataTable columns={coverColumns} rows={coverRows(cover)} emptyText="No fields extracted." maxHeight={240} />
            </>
          )}
          {cover?.error && (
            <div style={{ marginTop: space.sm, color: palette.danger, fontSize: 12 }}>
              Cover-field OCR failed: {cover.error}
            </div>
          )}
          {mark && !mark.error && (
            <>
              <div style={{ margin: `${space.md}px 0 ${space.xs}px`, fontSize: 12, fontWeight: 600 }}>
                Handwritten mark
              </div>
              <div style={{ marginBottom: space.xs, fontSize: 13 }}>
                {mark.mark != null ? (
                  <>
                    Extracted mark: <strong>{mark.mark}</strong> {confidenceCell(mark.mark_confidence)}
                  </>
                ) : (
                  <span style={{ color: palette.textMuted }}>No candidates found.</span>
                )}
              </div>
              <DataTable columns={markColumns} rows={markRows(mark)} emptyText="No candidates extracted." maxHeight={240} />
            </>
          )}
        </div>
      );
    }
    if (result.kind === "run") {
      const d = result.data || {};
      const rows = [
        ["Run ID", d.run_id],
        ["Status", d.status],
        ["Pages", d.page_count],
        ["Errors", d.errors && d.errors.length ? d.errors.join("; ") : "none"],
      ];
      return (
        <div style={{ width: "100%", display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 16px" }}>
          {rows.map(([k, v]) => (
            <Fragment key={k}>
              <span style={{ color: palette.textMuted, fontSize: 13 }}>{k}</span>
              <span style={{ fontFamily: MONO, fontSize: 13 }}>{String(v ?? "—")}</span>
            </Fragment>
          ))}
        </div>
      );
    }
    return (
      <span style={{ color: palette.textMuted, fontSize: 14 }}>
        Pick a sample image, or create a run.
      </span>
    );
  };

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, fontFamily: font.body, color: palette.text, padding: space.lg }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: space.lg }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>Debug</h1>
        <Button variant="subtle" onClick={() => navigate("/home")}>← Back to Login</Button>
      </div>

      <Card
        style={{
          maxWidth: 880,
          marginBottom: space.lg,
          minHeight: 260,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {renderResult()}
      </Card>

      {error && (
        <div style={{ marginBottom: space.md, padding: "10px 14px", background: palette.dangerBg, border: `1px solid ${palette.danger}`, borderRadius: 8, fontSize: 13, color: palette.danger, maxWidth: 880 }}>
          {error}
        </div>
      )}

      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: space.xs,
          marginBottom: space.sm,
          fontSize: 13,
          color: palette.text,
          userSelect: "none",
          cursor: "pointer",
        }}
      >
        <input
          type="checkbox"
          checked={applyOverlay}
          onChange={(e) => setApplyOverlay(e.target.checked)}
        />
        Apply rig overlay
      </label>

      <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
        <Button onClick={handleCreateRun} disabled={!!busy}>
          {busy === "run" ? "Capturing…" : "Create 1 Run"}
        </Button>
        <Button onClick={() => pickImage("cover")} disabled={!!busy}>
          {busy === "cover" ? "Scanning…" : "Scan Front Cover Only"}
        </Button>
        <Button onClick={() => pickImage("mark")} disabled={!!busy}>
          {busy === "mark" ? "Scanning…" : "Scan Mark Regions"}
        </Button>
        <Button onClick={() => pickImage("outline")} disabled={!!busy}>
          {busy === "outline" ? "Outlining…" : "Outline Page Frame Only"}
        </Button>
        <Button onClick={() => pickImage("booklet")} disabled={!!busy}>
          {busy === "booklet" ? "Testing…" : "Test Full Extraction (ZIP or PNG)"}
        </Button>
      </div>

      <input ref={fileInputRef} type="file" accept="image/*,.zip" style={{ display: "none" }} onChange={onFileSelected} />
    </div>
  );
}
