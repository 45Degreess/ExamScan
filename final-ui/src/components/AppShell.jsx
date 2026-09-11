import { Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import Button from "./Button.jsx";
import { font, palette, space } from "../theme.js";

export default function AppShell() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    try {
      await signOut();
    } finally {
      navigate("/login", { replace: true });
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, color: palette.text, fontFamily: font.body }}>
      <header
        style={{
          minHeight: 58,
          padding: `0 ${space.lg}px`,
          background: palette.surface,
          borderBottom: `1px solid ${palette.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: space.md,
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          onClick={() => navigate("/")}
          style={{ border: 0, background: "transparent", padding: 0, fontWeight: 700, fontSize: 17, cursor: "pointer" }}
        >
          ExamScan
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: space.sm, flexWrap: "wrap" }}>
          {user.role === "admin" && <Button variant="subtle" onClick={() => navigate("/admin/users")}>Staff</Button>}
          <span style={{ fontSize: 12.5, color: palette.textMuted }}>
            {user.name} · {user.uct_id}
          </span>
          <Button onClick={handleLogout}>Sign out</Button>
        </div>
      </header>
      <Outlet />
    </div>
  );
}
