import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import FormField, { TextInput } from "../components/FormField.jsx";

export default function StartupPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState("login"); // "login" | "signup"

  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  const [signupName, setSignupName] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [signupConfirmPassword, setSignupConfirmPassword] = useState("");

  const canLogin = loginEmail.trim() && loginPassword.trim();
  const canSignup =
    signupName.trim() && signupEmail.trim() && signupPassword.trim() && signupConfirmPassword.trim();

  const handleLogin = (e) => {
    e.preventDefault();
    if (!canLogin) return;
    navigate("/home");
  };

  const handleSignup = (e) => {
    e.preventDefault();
    // Sign-up is UI scaffolding only — no account creation flow yet.
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
        justifyContent: "center",
        padding: `${space.xl}px ${space.lg}px`,
      }}
    >
      <h1 style={{ fontSize: 30, fontWeight: 700, margin: `0 0 ${space.xs}px` }}>Welcome to ExamScan</h1>
      <p style={{ fontSize: 14, color: palette.textMuted, margin: `0 0 ${space.xl}px` }}>
        Sign in to start scanning, or create an account to get started.
      </p>

      <Card style={{ width: "100%", maxWidth: 420 }}>
        <div
          style={{
            display: "flex",
            marginBottom: space.lg,
            border: `1px solid ${palette.border}`,
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          <button
            type="button"
            onClick={() => setMode("login")}
            style={{
              flex: 1,
              padding: "9px 0",
              border: "none",
              cursor: "pointer",
              fontFamily: font.body,
              fontSize: 13.5,
              fontWeight: 600,
              background: mode === "login" ? palette.primary : palette.surface,
              color: mode === "login" ? "#fff" : palette.textMuted,
              transition: "background 0.15s, color 0.15s",
            }}
          >
            Log In
          </button>
          <button
            type="button"
            onClick={() => setMode("signup")}
            style={{
              flex: 1,
              padding: "9px 0",
              border: "none",
              cursor: "pointer",
              fontFamily: font.body,
              fontSize: 13.5,
              fontWeight: 600,
              background: mode === "signup" ? palette.primary : palette.surface,
              color: mode === "signup" ? "#fff" : palette.textMuted,
              transition: "background 0.15s, color 0.15s",
            }}
          >
            Sign Up
          </button>
        </div>

        {mode === "login" ? (
          <form onSubmit={handleLogin}>
            <FormField label="Email">
              <TextInput
                type="email"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                placeholder="you@example.com"
                required
              />
            </FormField>
            <FormField label="Password">
              <TextInput
                type="password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </FormField>
            <Button type="submit" variant="primary" disabled={!canLogin} style={{ width: "100%", marginTop: space.sm }}>
              Login
            </Button>
          </form>
        ) : (
          <form onSubmit={handleSignup}>
            <FormField label="Name">
              <TextInput
                value={signupName}
                onChange={(e) => setSignupName(e.target.value)}
                placeholder="Your name"
                required
              />
            </FormField>
            <FormField label="Email">
              <TextInput
                type="email"
                value={signupEmail}
                onChange={(e) => setSignupEmail(e.target.value)}
                placeholder="you@example.com"
                required
              />
            </FormField>
            <FormField label="Password">
              <TextInput
                type="password"
                value={signupPassword}
                onChange={(e) => setSignupPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </FormField>
            <FormField label="Confirm Password">
              <TextInput
                type="password"
                value={signupConfirmPassword}
                onChange={(e) => setSignupConfirmPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </FormField>
            <Button type="submit" variant="primary" disabled={!canSignup} style={{ width: "100%", marginTop: space.sm }}>
              Sign Up
            </Button>
          </form>
        )}
      </Card>
    </div>
  );
}
