import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import StatusDot from "../components/StatusDot.jsx";
import { useSession } from "../context/SessionContext.jsx";
import { listSessions } from "../api/sessions.js";

export default function LoginPage() {
  const navigate = useNavigate();
  const { backendOnline, piOnline } = useSession();
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [sessions, setSessions] = useState([]);

  // GET /sessions — load once the backend health check passes.
  useEffect(() => {
    if (!backendOnline) return;
    let cancelled = false;
    listSessions()
      .then((s) => !cancelled && setSessions(s))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [backendOnline]);

  const handleViewSession = () => {
    if (!selectedSessionId) return;
    navigate(`/sessions/${selectedSessionId}`);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: palette.bg,
        fontFamily: font.body,
        color: palette.text,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: `${space.xl}px ${space.lg}px`,
      }}
    >
      <h1 style={{ fontSize: 30, fontWeight: 700, margin: `${space.xl}px 0 ${space.xl}px` }}>
        Welcome to ExamScan
      </h1>

      <div
        style={{
          display: "flex",
          gap: space.lg,
          width: "100%",
          maxWidth: 920,
          flexWrap: "wrap",
        }}
      >
        {/* Left — connection list (static, non-interactive) */}
        <Card title="Connection" style={{ flex: 1, minWidth: 220 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
            <StatusDot status={backendOnline ? "green" : "red"} label="Backend" />
            <StatusDot
              status={piOnline ? "green" : "red"}
              label="Raspberry Pi"
              title="Live check via GET /pi/health (proxied to the Pi hardware server)"
            />
          </div>
        </Card>

        {/* Middle — session actions, gated on backend connection */}
        <Card title="Session" style={{ flex: 1.4, minWidth: 260 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
            <Button variant="primary" disabled={!backendOnline} onClick={() => navigate("/sessions/new")}>
              Start New Scanning Session
            </Button>

            <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
              <select
                value={selectedSessionId}
                onChange={(e) => setSelectedSessionId(e.target.value)}
                disabled={!backendOnline || sessions.length === 0}
                style={{
                  padding: "9px 12px",
                  borderRadius: 6,
                  border: `1px solid ${palette.borderStrong}`,
                  fontFamily: font.body,
                  fontSize: 13.5,
                  color: palette.text,
                  background: palette.surface,
                }}
              >
                <option value="">
                  {sessions.length === 0 ? "No previous sessions" : "Select a previous session…"}
                </option>
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.sessionCode} — {s.courseCode}
                  </option>
                ))}
              </select>
              <Button disabled={!backendOnline || !selectedSessionId} onClick={handleViewSession}>
                View Session
              </Button>
            </div>
          </div>
        </Card>

        {/* Right — debug page entry point, always enabled */}
        <Card title="Debug" style={{ flex: 1, minWidth: 220 }}>
          <p style={{ fontSize: 12.5, color: palette.textMuted, marginTop: 0 }}>
            Trigger individual ExamScan components in isolation.
          </p>
          <Button onClick={() => navigate("/debug")}>Open Debug Page</Button>
        </Card>
      </div>
    </div>
  );
}
