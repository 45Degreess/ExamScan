import { useState, useRef, useCallback, useEffect } from "react";

/*
 * DocScanner — React Frontend
 * ============================
 * Aesthetic: "Darkroom" — matte black + amber accents + film-grain texture.
 * Inspired by analog photographic equipment and professional scanning stations.
 */

const API_BASE = "/api";

/* ── Inline styles (no external CSS needed) ──────────────────────────── */

const palette = {
  bg: "#0e0e10",
  surface: "#18181c",
  surfaceHover: "#222228",
  border: "#2a2a30",
  borderFocus: "#d4a054",
  amber: "#d4a054",
  amberMuted: "rgba(212,160,84,0.12)",
  amberGlow: "rgba(212,160,84,0.35)",
  text: "#e8e4de",
  textMuted: "#8a8680",
  danger: "#c44d56",
  dangerBg: "rgba(196,77,86,0.1)",
  success: "#5cb87a",
  successBg: "rgba(92,184,122,0.08)",
};

const font = {
  display: "'DM Serif Display', 'Georgia', serif",
  body: "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
};

/* ── Helper: grain overlay via SVG data URI ──────────────────────────── */
const grainSvg = `<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.04'/></svg>`;
const grainUrl = `url("data:image/svg+xml,${encodeURIComponent(grainSvg)}")`;

/* ── Component ───────────────────────────────────────────────────────── */

export default function DocScanner() {
  const [sourceImage, setSourceImage] = useState(null);      // File object
  const [previewUrl, setPreviewUrl] = useState(null);        // data URL for preview
  const [detectionUrl, setDetectionUrl] = useState(null);    // preview with corners
  const [scannedUrl, setScannedUrl] = useState(null);        // final result blob URL
  const [enhance, setEnhance] = useState(true);
  const [loading, setLoading] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [splitting, setSplitting] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [processResult, setProcessResult] = useState(null);
  const [coverData, setCoverData] = useState(null);
  const [error, setError] = useState(null);
  const [webcamActive, setWebcamActive] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [phase, setPhase] = useState("upload");              // upload | preview | result

  const fileInputRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);

  /* ── File handling ──────────────────────────────────────────────────── */

  const handleFile = useCallback((file) => {
    if (!file || !file.type.startsWith("image/")) {
      setError("Please select a valid image file.");
      return;
    }
    setError(null);
    setSourceImage(file);
    setScannedUrl(null);
    setDetectionUrl(null);
    const reader = new FileReader();
    reader.onload = (e) => {
      setPreviewUrl(e.target.result);
      setPhase("preview");
    };
    reader.readAsDataURL(file);
  }, []);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }, [handleFile]);

  /* ── Webcam ─────────────────────────────────────────────────────────── */

  const startWebcam = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
      }
      setWebcamActive(true);
      setError(null);
    } catch {
      setError("Could not access camera. Check permissions.");
    }
  };

  const captureFrame = () => {
    if (!videoRef.current || !canvasRef.current) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      const file = new File([blob], "capture.jpg", { type: "image/jpeg" });
      handleFile(file);
      stopWebcam();
    }, "image/jpeg", 0.92);
  };

  const stopWebcam = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setWebcamActive(false);
  };

  useEffect(() => () => stopWebcam(), []);

  /* ── API calls ──────────────────────────────────────────────────────── */

  const detectCorners = async () => {
    if (!sourceImage) return;
    setDetecting(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", sourceImage);
      const res = await fetch(`${API_BASE}/detect-preview`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Detection failed");
      }
      const blob = await res.blob();
      setDetectionUrl(URL.createObjectURL(blob));
    } catch (e) {
      setError(e.message);
    } finally {
      setDetecting(false);
    }
  };

  const scanDocument = async () => {
    if (!sourceImage) return;
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", sourceImage);
      fd.append("enhance", String(enhance));
      const res = await fetch(`${API_BASE}/scan`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Scan failed");
      }
      const blob = await res.blob();
      setScannedUrl(URL.createObjectURL(blob));
      setPhase("result");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const extractCover = async () => {
    if (!sourceImage) return;
    setExtracting(true);
    setError(null);
    setCoverData(null);
    try {
      const fd = new FormData();
      fd.append("file", sourceImage);
      const res = await fetch(`${API_BASE}/extract-cover`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Extraction failed");
      }
      const data = await res.json();
      setCoverData(data);
      setPhase("cover");
    } catch (e) {
      setError(e.message);
    } finally {
      setExtracting(false);
    }
  };

  const processPage = async () => {
    if (!sourceImage) return;
    setProcessing(true);
    setError(null);
    setProcessResult(null);
    try {
      const fd = new FormData();
      fd.append("file", sourceImage);
      fd.append("enhance", String(enhance));
      const res = await fetch(`${API_BASE}/process-page`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Processing failed");
      }
      const data = await res.json();
      setProcessResult(data);
      setPhase("process_result");
    } catch (e) {
      setError(e.message);
    } finally {
      setProcessing(false);
    }
  };

  const splitBooklet = async () => {
    if (!sourceImage) return;
    setSplitting(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", sourceImage);
      fd.append("enhance", String(enhance));
      const res = await fetch(`${API_BASE}/split-booklet`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Split failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "booklet_pages.zip";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setSplitting(false);
    }
  };

  const reset = () => {
    setSourceImage(null);
    setPreviewUrl(null);
    setDetectionUrl(null);
    setScannedUrl(null);
    setCoverData(null);
    setProcessResult(null);
    setError(null);
    setPhase("upload");
    stopWebcam();
  };

  const handleSampleSelect = useCallback(async (filename) => {
    try {
      const res = await fetch(`${API_BASE}/samples/${encodeURIComponent(filename)}`);
      if (!res.ok) throw new Error("Failed to load sample image");
      const blob = await res.blob();
      const ext = filename.split(".").pop().toLowerCase();
      const mime = ext === "png" ? "image/png" : "image/jpeg";
      handleFile(new File([blob], filename, { type: mime }));
    } catch (e) {
      setError(e.message);
    }
  }, [handleFile]);

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <div style={{
      minHeight: "100vh",
      background: `${palette.bg}`,
      backgroundImage: grainUrl,
      backgroundSize: "200px 200px",
      fontFamily: font.body,
      color: palette.text,
      display: "flex",
      flexDirection: "row",
      alignItems: "flex-start",
    }}>
      <SamplePanel onSelect={handleSampleSelect} />
      <div style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "40px 20px",
        minWidth: 0,
      }}>
      {/* ── Header ───────────────────────────────────────────────── */}
      <header style={{ textAlign: "center", marginBottom: 48 }}>
        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 8,
        }}>
          <div style={{
            width: 36, height: 36,
            borderRadius: 8,
            background: `linear-gradient(135deg, ${palette.amber}, #b8863a)`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 18,
            boxShadow: `0 0 20px ${palette.amberGlow}`,
          }}>⬡</div>
          <h1 style={{
            fontFamily: font.display,
            fontSize: 32,
            fontWeight: 400,
            letterSpacing: "0.02em",
            margin: 0,
          }}>DocScanner</h1>
        </div>
        <p style={{
          color: palette.textMuted,
          fontSize: 12,
          letterSpacing: "0.15em",
          textTransform: "uppercase",
          margin: 0,
        }}>Perspective-corrected document scanning</p>
      </header>

      {/* ── Main card ────────────────────────────────────────────── */}
      <div style={{
        width: "100%",
        maxWidth: 720,
        background: palette.surface,
        border: `1px solid ${palette.border}`,
        borderRadius: 16,
        overflow: "hidden",
      }}>

        {/* ── Upload Phase ───────────────────────────────────────── */}
        {phase === "upload" && !webcamActive && (
          <div
            onDrop={onDrop}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onClick={() => fileInputRef.current?.click()}
            style={{
              padding: "80px 40px",
              textAlign: "center",
              cursor: "pointer",
              border: `2px dashed ${dragOver ? palette.amber : palette.border}`,
              borderRadius: 12,
              margin: 20,
              transition: "all 0.3s ease",
              background: dragOver ? palette.amberMuted : "transparent",
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              style={{ display: "none" }}
              onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            />
            <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.6 }}>📄</div>
            <p style={{ fontSize: 15, marginBottom: 6 }}>
              Drop an image here or <span style={{ color: palette.amber, textDecoration: "underline" }}>browse</span>
            </p>
            <p style={{ fontSize: 12, color: palette.textMuted }}>
              JPG, PNG, WEBP — photo of a document on a contrasting background
            </p>
          </div>
        )}

        {/* ── Webcam Phase ───────────────────────────────────────── */}
        {phase === "upload" && webcamActive && (
          <div style={{ position: "relative" }}>
            <video
              ref={videoRef}
              style={{ width: "100%", display: "block", borderRadius: "16px 16px 0 0" }}
              playsInline
              muted
            />
            {/* Viewfinder overlay */}
            <div style={{
              position: "absolute", inset: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              pointerEvents: "none",
            }}>
              <div style={{
                width: "70%", height: "80%",
                border: `2px solid ${palette.amber}`,
                borderRadius: 12,
                boxShadow: `0 0 0 9999px rgba(0,0,0,0.4), inset 0 0 30px ${palette.amberGlow}`,
              }} />
            </div>
            <div style={{ display: "flex", gap: 12, padding: 20, justifyContent: "center" }}>
              <Btn onClick={captureFrame} primary>⏺ Capture</Btn>
              <Btn onClick={stopWebcam}>Cancel</Btn>
            </div>
          </div>
        )}

        {/* ── Camera button (upload phase only) ──────────────────── */}
        {phase === "upload" && !webcamActive && (
          <div style={{
            display: "flex", justifyContent: "center",
            padding: "0 20px 24px",
          }}>
            <Btn onClick={startWebcam}>
              📷 Use Camera
            </Btn>
          </div>
        )}

        {/* ── Preview Phase ──────────────────────────────────────── */}
        {phase === "preview" && (
          <div>
            <div style={{ display: "flex", gap: 12, padding: 20, flexWrap: "wrap" }}>
              {/* Original preview */}
              <div style={{ flex: 1, minWidth: 240 }}>
                <Label>Original</Label>
                <ImgFrame src={previewUrl} alt="Original" />
              </div>
              {/* Detection preview */}
              {detectionUrl && (
                <div style={{ flex: 1, minWidth: 240 }}>
                  <Label>Detected Corners</Label>
                  <ImgFrame src={detectionUrl} alt="Detected" />
                </div>
              )}
            </div>

            {/* ── Controls ────────────────────────────────────────── */}
            <div style={{
              padding: "0 20px 20px",
              display: "flex", flexDirection: "column", gap: 16,
            }}>
              {/* Enhance toggle */}
              <div
                onClick={() => setEnhance(!enhance)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  cursor: "pointer", userSelect: "none",
                }}
              >
                <div style={{
                  width: 40, height: 22, borderRadius: 11,
                  background: enhance ? palette.amber : palette.border,
                  position: "relative",
                  transition: "background 0.2s",
                }}>
                  <div style={{
                    width: 16, height: 16, borderRadius: 8,
                    background: "#fff",
                    position: "absolute", top: 3,
                    left: enhance ? 21 : 3,
                    transition: "left 0.2s",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
                  }} />
                </div>
                <span style={{ fontSize: 13 }}>
                  High-contrast enhancement
                </span>
              </div>

              {/* Action buttons */}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <Btn onClick={detectCorners} disabled={detecting}>
                  {detecting ? "⏳ Detecting…" : "🔍 Detect Corners"}
                </Btn>
                <Btn onClick={scanDocument} primary disabled={loading}>
                  {loading ? "⏳ Scanning…" : "⚡ Scan Document"}
                </Btn>
                <Btn onClick={processPage} primary disabled={processing}>
                  {processing ? "⏳ Processing…" : "⬡ Process Page"}
                </Btn>
                <Btn onClick={extractCover} disabled={extracting} style={{ borderColor: palette.amber, color: palette.amber }}>
                  {extracting ? "⏳ Extracting…" : "📋 Extract Cover"}
                </Btn>
                <Btn onClick={splitBooklet} disabled={splitting} style={{ borderColor: palette.amber, color: palette.amber }}>
                  {splitting ? "⏳ Splitting…" : "📖 Split Booklet"}
                </Btn>
                <Btn onClick={reset} danger>✕ Reset</Btn>
              </div>
            </div>
          </div>
        )}

        {/* ── Result Phase ───────────────────────────────────────── */}
        {phase === "result" && scannedUrl && (
          <div style={{ padding: 20 }}>
            <Label>Scanned Result</Label>
            <ImgFrame src={scannedUrl} alt="Scanned" />
            <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
              <a
                href={scannedUrl}
                download="scanned.png"
                style={{ textDecoration: "none" }}
              >
                <Btn primary>⬇ Download PNG</Btn>
              </a>
              <Btn onClick={() => setPhase("preview")}>← Back to Preview</Btn>
              <Btn onClick={reset} danger>✕ New Scan</Btn>
            </div>
          </div>
        )}

        {/* ── Cover Extraction Result ────────────────────────────── */}
        {phase === "cover" && coverData && (
          <div style={{ padding: 20 }}>
            <Label>Extracted Cover Fields</Label>
            <div style={{
              border: `1px solid ${palette.border}`,
              borderRadius: 10,
              overflow: "hidden",
            }}>
              {Object.entries(coverData.fields).map(([key, value], i) => (
                <div key={key} style={{
                  display: "grid",
                  gridTemplateColumns: "180px 1fr",
                  borderBottom: i < Object.keys(coverData.fields).length - 1
                    ? `1px solid ${palette.border}` : "none",
                }}>
                  <div style={{
                    padding: "12px 16px",
                    background: palette.amberMuted,
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: palette.amber,
                    borderRight: `1px solid ${palette.border}`,
                    display: "flex",
                    alignItems: "center",
                  }}>
                    {key.replace(/_/g, " ")}
                  </div>
                  <div style={{
                    padding: "12px 16px",
                    fontSize: 14,
                    color: value ? palette.text : palette.textMuted,
                    fontStyle: value ? "normal" : "italic",
                  }}>
                    {value || "—"}
                  </div>
                </div>
              ))}
            </div>
            <div style={{
              marginTop: 10,
              fontSize: 11,
              color: palette.textMuted,
            }}>
              Canonical scan size: {coverData.scan_dimensions.width} × {coverData.scan_dimensions.height} px
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
              <Btn onClick={() => setPhase("preview")}>← Back to Preview</Btn>
              <Btn onClick={reset} danger>✕ New Scan</Btn>
            </div>
          </div>
        )}

        {/* ── Process Page Result ────────────────────────────────── */}
        {phase === "process_result" && processResult && (
          <div style={{ padding: 20 }}>
            {processResult.type === "first_page" ? (
              <>
                <Label>First Page — Scanned</Label>
                <ImgFrame
                  src={`data:image/png;base64,${processResult.scanned_image}`}
                  alt="Scanned first page"
                />
                <Label style={{ marginTop: 16 }}>OCR — Written Text</Label>
                <pre style={{
                  background: palette.bg,
                  border: `1px solid ${palette.border}`,
                  borderRadius: 8,
                  padding: 16,
                  fontSize: 13,
                  whiteSpace: "pre-wrap",
                  color: palette.text,
                  maxHeight: 300,
                  overflowY: "auto",
                  fontFamily: font.body,
                  margin: 0,
                }}>
                  {processResult.ocr_text || "— no text detected —"}
                </pre>
              </>
            ) : (
              <>
                <Label>Booklet — Page 1</Label>
                <ImgFrame
                  src={`data:image/png;base64,${processResult.pages[0].scanned_image}`}
                  alt="Page 1"
                />
                <Label style={{ marginTop: 16 }}>Booklet — Page 2</Label>
                <ImgFrame
                  src={`data:image/png;base64,${processResult.pages[1].scanned_image}`}
                  alt="Page 2"
                />
              </>
            )}
            <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
              <Btn onClick={() => setPhase("preview")}>← Back</Btn>
              <Btn onClick={reset} danger>✕ New Scan</Btn>
            </div>
          </div>
        )}

        {/* ── Error banner ───────────────────────────────────────── */}
        {error && (
          <div style={{
            margin: "0 20px 20px",
            padding: "12px 16px",
            background: palette.dangerBg,
            border: `1px solid ${palette.danger}`,
            borderRadius: 8,
            fontSize: 13,
            color: palette.danger,
          }}>
            ⚠ {error}
          </div>
        )}
      </div>

      {/* ── Pipeline info ────────────────────────────────────────── */}
      <div style={{
        maxWidth: 720, width: "100%",
        marginTop: 32, padding: "0 4px",
      }}>
        <p style={{
          fontSize: 11,
          color: palette.textMuted,
          textAlign: "center",
          lineHeight: 1.7,
          letterSpacing: "0.03em",
        }}>
          Pipeline: Gaussian blur → Canny edge detection → contour approximation →
          4-point perspective transform → CLAHE + adaptive threshold enhancement
        </p>
      </div>

      {/* Hidden canvas for webcam capture */}
      <canvas ref={canvasRef} style={{ display: "none" }} />
      </div>
    </div>
  );
}

/* ── Reusable sub-components ─────────────────────────────────────────── */

function Btn({ children, primary, danger, disabled, onClick, style: s }) {
  const [hovered, setHovered] = useState(false);
  const base = {
    padding: "10px 20px",
    borderRadius: 8,
    border: "1px solid",
    fontSize: 13,
    fontFamily: font.body,
    fontWeight: 500,
    cursor: disabled ? "not-allowed" : "pointer",
    transition: "all 0.2s",
    opacity: disabled ? 0.5 : 1,
    whiteSpace: "nowrap",
  };
  let colors;
  if (primary) {
    colors = {
      background: hovered ? palette.amber : "transparent",
      borderColor: palette.amber,
      color: hovered ? palette.bg : palette.amber,
    };
  } else if (danger) {
    colors = {
      background: hovered ? palette.dangerBg : "transparent",
      borderColor: palette.danger,
      color: palette.danger,
    };
  } else {
    colors = {
      background: hovered ? palette.surfaceHover : "transparent",
      borderColor: palette.border,
      color: palette.text,
    };
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ ...base, ...colors, ...s }}
    >
      {children}
    </button>
  );
}

function Label({ children, style: s }) {
  return (
    <div style={{
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: "0.12em",
      textTransform: "uppercase",
      color: palette.textMuted,
      marginBottom: 8,
      ...s,
    }}>
      {children}
    </div>
  );
}

function SamplePanel({ onSelect }) {
  const [open, setOpen] = useState(true);
  const [samples, setSamples] = useState([]);
  const [fetching, setFetching] = useState(true);
  const [hovered, setHovered] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/samples`)
      .then((r) => r.json())
      .then((d) => setSamples(d.files || []))
      .catch(() => {})
      .finally(() => setFetching(false));
  }, []);

  return (
    <div style={{
      width: open ? 200 : 40,
      minHeight: "100vh",
      background: palette.surface,
      borderRight: `1px solid ${palette.border}`,
      flexShrink: 0,
      transition: "width 0.22s ease",
      overflow: "hidden",
      position: "sticky",
      top: 0,
      display: "flex",
      flexDirection: "column",
    }}>
      {/* Toggle */}
      <button
        onClick={() => setOpen((o) => !o)}
        title={open ? "Collapse sample panel" : "Browse sample images"}
        style={{
          width: 40,
          height: 40,
          flexShrink: 0,
          border: "none",
          background: "transparent",
          color: palette.amber,
          cursor: "pointer",
          fontSize: 14,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {open ? "◀" : "▶"}
      </button>

      {open && (
        <div style={{ padding: "0 10px 16px", overflowY: "auto", flex: 1 }}>
          <div style={{
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: palette.textMuted,
            marginBottom: 10,
            whiteSpace: "nowrap",
          }}>
            Sample Images
          </div>

          {fetching && (
            <div style={{ fontSize: 11, color: palette.textMuted }}>Loading…</div>
          )}
          {!fetching && samples.length === 0 && (
            <div style={{ fontSize: 11, color: palette.textMuted }}>No samples found</div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {samples.map((name) => (
              <div
                key={name}
                onClick={() => onSelect(name)}
                onMouseEnter={() => setHovered(name)}
                onMouseLeave={() => setHovered(null)}
                style={{
                  cursor: "pointer",
                  borderRadius: 8,
                  overflow: "hidden",
                  border: `1px solid ${hovered === name ? palette.amber : palette.border}`,
                  transition: "border-color 0.18s",
                  background: hovered === name ? palette.amberMuted : "transparent",
                }}
              >
                <img
                  src={`${API_BASE}/samples/${encodeURIComponent(name)}`}
                  alt={name}
                  style={{ width: "100%", height: 72, objectFit: "cover", display: "block" }}
                />
                <div style={{
                  padding: "5px 7px",
                  fontSize: 10,
                  color: hovered === name ? palette.amber : palette.textMuted,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  transition: "color 0.18s",
                }}>
                  {name}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ImgFrame({ src, alt }) {
  return (
    <div style={{
      border: `1px solid ${palette.border}`,
      borderRadius: 10,
      overflow: "hidden",
      background: "#111",
      lineHeight: 0,
    }}>
      <img
        src={src}
        alt={alt}
        style={{
          width: "100%",
          display: "block",
          objectFit: "contain",
          maxHeight: 460,
        }}
      />
    </div>
  );
}
