import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Button from "../components/Button.jsx";
import Card from "../components/Card.jsx";
import FormField, { TextInput } from "../components/FormField.jsx";
import StatusDot from "../components/StatusDot.jsx";
import { checkBackendHealth } from "../api/sessions.js";
import { useAuth } from "../context/AuthContext.jsx";
import { font, palette, space } from "../theme.js";

export default function LoginPage() {
  const { user, loading, signIn, requestPassword } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [backendOnline, setBackendOnline] = useState(false);
  const [uctId, setUctId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    checkBackendHealth().then(setBackendOnline);
  }, []);

  useEffect(() => {
    if (!loading && user) navigate(location.state?.from || "/", { replace: true });
  }, [loading, user, navigate, location.state]);

  const submitLogin = async (event) => {
    event.preventDefault();
    setError("");
    setMessage("");
    setBusy(true);
    try {
      await signIn(uctId, password);
      navigate(location.state?.from || "/", { replace: true });
    } catch (err) {
      setError(err.message || "Incorrect UCT ID or password.");
    } finally {
      setBusy(false);
    }
  };

  const emailPassword = async () => {
    if (!uctId.trim()) {
      setError("Enter your UCT ID first.");
      return;
    }
    setError("");
    setMessage("");
    setBusy(true);
    try {
      const result = await requestPassword(uctId);
      setMessage(result.message);
    } catch (err) {
      setError(err.message || "The password request could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main
      style={{
        minHeight: "100vh",
        background: palette.bg,
        color: palette.text,
        fontFamily: font.body,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: space.lg,
      }}
    >
      <div style={{ width: "100%", maxWidth: 430 }}>
        <h1 style={{ textAlign: "center", margin: `0 0 ${space.lg}px`, fontSize: 30 }}>ExamScan</h1>
        <Card title="Staff sign in" subtitle="Use your registered UCT staff ID and emailed password.">
          <form onSubmit={submitLogin}>
            <FormField label="UCT ID">
              <TextInput
                value={uctId}
                onChange={(event) => setUctId(event.target.value.toUpperCase())}
                autoComplete="username"
                autoCapitalize="characters"
                required
                autoFocus
              />
            </FormField>
            <FormField label="Password">
              <TextInput
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </FormField>

            {error && <p role="alert" style={{ color: palette.danger, fontSize: 13, margin: `0 0 ${space.md}px` }}>{error}</p>}
            {message && <p role="status" style={{ color: palette.success, fontSize: 13, margin: `0 0 ${space.md}px` }}>{message}</p>}

            <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
              <Button type="submit" variant="primary" disabled={busy || !backendOnline}>Sign in</Button>
              <Button type="button" disabled={busy || !backendOnline} onClick={emailPassword}>Email me a password</Button>
            </div>
          </form>
          <div style={{ marginTop: space.lg, paddingTop: space.md, borderTop: `1px solid ${palette.border}` }}>
            <StatusDot status={backendOnline ? "green" : "red"} label={backendOnline ? "Backend online" : "Backend offline"} />
          </div>
        </Card>
      </div>
    </main>
  );
}
