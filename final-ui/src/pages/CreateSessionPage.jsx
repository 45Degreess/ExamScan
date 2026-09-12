import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import FormField, { TextInput } from "../components/FormField.jsx";
import { createSession } from "../api/sessions.js";
import { useSession } from "../context/SessionContext.jsx";

export default function CreateSessionPage() {
  const navigate = useNavigate();
  const { startSession } = useSession();

  const [sessionName, setSessionName] = useState("");
  const [operatorName, setOperatorName] = useState("");
  const [courseCode, setCourseCode] = useState("");
  const [testTotal, setTestTotal] = useState("");
  const [date, setDate] = useState("");
  const [studentListFile, setStudentListFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const canSubmit =
    sessionName.trim() && operatorName.trim() && courseCode.trim() && testTotal !== "" && date;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      // Real call: POST /sessions (software/routes.py). When a CSV is attached
      // the backend seeds the session_students roster from its Role=Student rows.
      const res = await createSession({
        sessionCode: sessionName.trim(),
        operatorName: operatorName.trim(),
        testDate: date,
        courseCode: courseCode.trim(),
        testTotal: Number(testTotal),
        classListFile: studentListFile,
      });

      startSession({
        id: res.session_id,
        sessionCode: res.session_code,
        operatorName: operatorName.trim(),
        courseCode: courseCode.trim(),
        date,
        hasRoster: !!studentListFile,
      });

      // With a class list, step through the Prepare page (review/deselect
      // expected students); without one there's nothing to prepare.
      navigate(studentListFile ? `/sessions/${res.session_id}/prepare` : `/sessions/${res.session_id}`);
    } catch (e2) {
      setError(e2.message);
    } finally {
      setSubmitting(false);
    }
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
      <h1 style={{ fontSize: 24, fontWeight: 700, margin: `${space.lg}px 0 ${space.xl}px` }}>
        Create Scanning Session
      </h1>

      <Card style={{ width: "100%", maxWidth: 520 }}>
        <form onSubmit={handleSubmit}>
          <FormField label="Session Name">
            <TextInput value={sessionName} onChange={(e) => setSessionName(e.target.value)} placeholder="e.g. CSC3003S Exam 2" required />
          </FormField>
          <FormField label="Operator Name">
            <TextInput value={operatorName} onChange={(e) => setOperatorName(e.target.value)} placeholder="Your name" required />
          </FormField>
          <FormField label="Course Code">
            <TextInput value={courseCode} onChange={(e) => setCourseCode(e.target.value)} placeholder="e.g. CSC3003S" required />
          </FormField>
          <FormField label="Test Total">
            <TextInput
              type="number"
              min="0"
              value={testTotal}
              onChange={(e) => setTestTotal(e.target.value)}
              placeholder="e.g. 100"
              required
            />
          </FormField>
          <FormField label="Date">
            <TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </FormField>
          <FormField label="Student List (optional)">
            <TextInput type="file" accept=".csv,.txt" onChange={(e) => setStudentListFile(e.target.files?.[0] || null)} />
          </FormField>

          {error && (
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
          )}

          <div style={{ display: "flex", gap: space.sm, justifyContent: "flex-end" }}>
            <Button variant="subtle" onClick={() => navigate("/home")}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={!canSubmit || submitting}>
              {submitting ? "Creating…" : "Create Session"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
