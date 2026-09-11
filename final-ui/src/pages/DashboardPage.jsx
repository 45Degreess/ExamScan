import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import StatusDot from "../components/StatusDot.jsx";
import { useSession } from "../context/SessionContext.jsx";
import { listSessions } from "../api/sessions.js";

export default function DashboardPage() {
  const navigate = useNavigate();
  const { backendOnline, piOnline } = useSession();
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [sessions, setSessions] = useState([]);

  useEffect(() => {
    if (!backendOnline) return;
    let cancelled = false;
    listSessions().then((items) => !cancelled && setSessions(items)).catch(() => {});
    return () => { cancelled = true; };
  }, [backendOnline]);

  return (
    <main style={{ background: palette.bg, fontFamily: font.body, color: palette.text, padding: `${space.xl}px ${space.lg}px` }}>
      <h1 style={{ fontSize: 30, fontWeight: 700, margin: `0 auto ${space.xl}px`, maxWidth: 920 }}>ExamScan dashboard</h1>
      <div style={{ display: "flex", gap: space.lg, width: "100%", maxWidth: 920, margin: "0 auto", flexWrap: "wrap" }}>
        <Card title="Connection" style={{ flex: 1, minWidth: 220 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
            <StatusDot status={backendOnline ? "green" : "red"} label="Backend" />
            <StatusDot status={piOnline ? "green" : "red"} label="Raspberry Pi" title="Live check through the protected Pi proxy" />
          </div>
        </Card>
        <Card title="Session" style={{ flex: 1.4, minWidth: 260 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
            <Button variant="primary" disabled={!backendOnline} onClick={() => navigate("/sessions/new")}>Start New Scanning Session</Button>
            <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
              <select
                value={selectedSessionId}
                onChange={(event) => setSelectedSessionId(event.target.value)}
                disabled={!backendOnline || sessions.length === 0}
                style={{ padding: "9px 12px", borderRadius: 6, border: `1px solid ${palette.borderStrong}`, fontFamily: font.body, fontSize: 13.5, color: palette.text, background: palette.surface }}
              >
                <option value="">{sessions.length === 0 ? "No previous sessions" : "Select a previous session…"}</option>
                {sessions.map((session) => <option key={session.id} value={session.id}>{session.sessionCode} — {session.courseCode}</option>)}
              </select>
              <Button disabled={!backendOnline || !selectedSessionId} onClick={() => navigate(`/sessions/${selectedSessionId}`)}>View Session</Button>
            </div>
          </div>
        </Card>
        <Card title="Debug" style={{ flex: 1, minWidth: 220 }}>
          <p style={{ fontSize: 12.5, color: palette.textMuted, marginTop: 0 }}>Trigger individual ExamScan components in isolation.</p>
          <Button onClick={() => navigate("/debug")}>Open Debug Page</Button>
        </Card>
      </div>
    </main>
  );
}
