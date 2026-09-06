import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import DataTable from "../components/DataTable.jsx";
import { TextInput } from "../components/FormField.jsx";
import { useSession } from "../context/SessionContext.jsx";
import { getSessionStudents, setExpectedStudents } from "../api/sessions.js";

// Sits between Create Session and View Session. Shows the imported class list
// (session_students, everyone expected by default) and lets the operator
// search + deselect anyone who won't sit the exam. Deselections are held
// locally and written in one PUT on "Proceed" — see
// docs/final-ui-api-requirements.md ("Create Session page — Student list").
export default function PrepareSessionPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { currentSession, loadSession } = useSession();

  const [session, setSession] = useState(null);
  const [students, setStudents] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    let s = currentSession;
    if (!s || String(s.id) !== String(sessionId)) {
      s = loadSession(sessionId);
    }
    if (!s) {
      navigate("/");
      return;
    }
    setSession(s);

    if (!s.sessionCode) {
      setError("This session has no code on record — recreate it.");
      setLoading(false);
      return;
    }

    setLoading(true);
    getSessionStudents(s.sessionCode)
      .then((data) => {
        if (cancelled) return;
        const rows = data.students || [];
        setStudents(rows);
        setSelected(new Set(rows.filter((r) => r.expected).map((r) => r.username)));
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return students;
    return students.filter(
      (s) => s.name.toLowerCase().includes(q) || s.username.toLowerCase().includes(q),
    );
  }, [students, search]);

  const toggle = (username) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(username) ? next.delete(username) : next.add(username);
      return next;
    });
  };

  const handleProceed = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const excluded = students
        .map((s) => s.username)
        .filter((u) => !selected.has(u));
      await setExpectedStudents(session.sessionCode, excluded);
      navigate(`/sessions/${sessionId}`);
    } catch (e) {
      setError(e.message);
      setSubmitting(false);
    }
  };

  const columns = [
    { key: "name", header: "Name" },
    { key: "username", header: "ID" },
    {
      key: "select",
      header: "",
      render: (row) => {
        const isSelected = selected.has(row.username);
        return (
          <Button
            variant={isSelected ? "primary" : "default"}
            style={{ padding: "4px 12px" }}
            onClick={() => toggle(row.username)}
            title={
              isSelected
                ? "Selected — expected to sit the exam. Click to deselect."
                : "Deselected — won't be flagged as missing. Click to re-select."
            }
          >
            {isSelected ? "Selected" : "Deselected"}
          </Button>
        );
      },
    },
  ];

  const errorBox = error && (
    <div
      style={{
        marginBottom: space.md,
        padding: "10px 14px",
        background: palette.dangerBg,
        border: `1px solid ${palette.danger}`,
        borderRadius: 8,
        fontSize: 13,
        color: palette.danger,
      }}
    >
      {error}
    </div>
  );

  return (
    <div
      style={{
        minHeight: "100vh",
        background: palette.bg,
        fontFamily: font.body,
        color: palette.text,
        padding: space.lg,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: space.lg,
        }}
      >
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>
            Prepare Session{session?.sessionCode ? ` — ${session.sessionCode}` : ""}
          </h1>
          <p style={{ fontSize: 13, color: palette.textMuted, margin: "6px 0 0" }}>
            {selected.size} of {students.length} students expected · deselect anyone
            who should not be flagged as missing.
          </p>
        </div>
        <Button variant="subtle" onClick={() => navigate("/")}>← Back to Login</Button>
      </div>

      <Card style={{ maxWidth: 720 }} title="Class List">
        {errorBox}

        {loading ? (
          <div style={{ padding: "32px 16px", textAlign: "center", color: palette.textMuted, fontSize: 13 }}>
            Loading class list…
          </div>
        ) : (
          <>
            <TextInput
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or ID…"
              style={{ marginBottom: space.md }}
            />
            <DataTable
              columns={columns}
              rows={filtered}
              rowStyle={(row) => (selected.has(row.username) ? null : { opacity: 0.45 })}
              emptyText={
                students.length === 0
                  ? "No students in the class list."
                  : "No students match your search."
              }
            />
          </>
        )}

        <div style={{ display: "flex", gap: space.sm, justifyContent: "flex-end", marginTop: space.lg }}>
          <Button
            variant="subtle"
            disabled={submitting}
            onClick={() => navigate(`/sessions/${sessionId}`)}
          >
            Skip
          </Button>
          <Button variant="primary" disabled={loading || submitting} onClick={handleProceed}>
            {submitting ? "Saving…" : "Proceed to Session"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
