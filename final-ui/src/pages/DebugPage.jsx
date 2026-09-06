import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import { detectPreview } from "../api/sessions.js";

export default function DebugPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [resultUrl, setResultUrl] = useState(null);
  const [statusText, setStatusText] = useState("Live feed functionality");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // MOCK: no real "create one run" hook is wired in this UI-only task — see
  // docs/final-ui-api-requirements.md ("Debug page — Create 1 Run").
  const handleCreateRun = () => {
    setResultUrl(null);
    setStatusText("MOCK: would create one run via the Pi's capture workflow.");
  };

  // MOCK: no standalone "front cover only" endpoint exists — see docs
  // ("Debug page — Scan Front Cover Only").
  const handleScanCover = () => {
    setResultUrl(null);
    setStatusText("MOCK: would OCR only the front cover region and render it here.");
  };

  // Real: calls POST /detect-preview (software/routes.py:249-270), an
  // existing backend capability, so this one is genuinely wired rather than
  // mocked. Requires the operator to pick a sample image.
  const handleOutlineFrame = () => {
    fileInputRef.current?.click();
  };

  const onFileSelected = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await detectPreview(file);
      setResultUrl(URL.createObjectURL(blob));
      setStatusText(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, fontFamily: font.body, color: palette.text, padding: space.lg }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: space.lg }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>Debug</h1>
        <Button variant="subtle" onClick={() => navigate("/")}>← Back to Login</Button>
      </div>

      <Card style={{ maxWidth: 640, marginBottom: space.lg, minHeight: 260, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {resultUrl ? (
          <img src={resultUrl} alt="Debug result" style={{ maxWidth: "100%", maxHeight: 400, borderRadius: 8 }} />
        ) : (
          <span style={{ color: palette.textMuted, fontSize: 14 }}>{busy ? "Processing…" : statusText}</span>
        )}
      </Card>

      {error && (
        <div style={{ marginBottom: space.md, padding: "10px 14px", background: palette.dangerBg, border: `1px solid ${palette.danger}`, borderRadius: 8, fontSize: 13, color: palette.danger, maxWidth: 640 }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
        <Button onClick={handleCreateRun}>Create 1 Run</Button>
        <Button onClick={handleScanCover}>Scan Front Cover Only</Button>
        <Button onClick={handleOutlineFrame} disabled={busy}>Outline Page Frame Only</Button>
      </div>

      <input ref={fileInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={onFileSelected} />
    </div>
  );
}
