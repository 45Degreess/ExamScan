import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import StatusDot from "../components/StatusDot.jsx";
import DataTable from "../components/DataTable.jsx";
import { useSession } from "../context/SessionContext.jsx";
import { listSessions } from "../api/sessions.js";

export default function DashboardPage() {
  const navigate = useNavigate();
  const { backendOnline, piOnline } = useSession();
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
            <DataTable
              maxHeight={400}
              emptyText={backendOnline ? "No previous sessions" : "Connect to the backend to see previous sessions"}
              columns={[
                { key: "session", header: "Session", render: (session) => `${session.sessionCode} — ${session.courseCode}` },
                {
                  key: "date",
                  header: "Date",
                  render: (session) => (session.date ? new Date(session.date).toLocaleDateString() : "—"),
                },
              ]}
              rows={sessions}
              rowStyle={() => ({ cursor: "pointer" })}
              onRowClick={(session) => navigate(`/sessions/${session.id}`)}
            />
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
