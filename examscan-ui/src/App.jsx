import { useState } from "react";
import './App.css'
import DocScanner from "./DocScanner";
import PdfDemo from "./PdfDemo";
import { palette, font } from "./theme.jsx";

export default function App() {
  const [tab, setTab] = useState("scanner");

  const tabStyle = (active) => ({
    padding: "10px 20px",
    fontSize: 12,
    fontFamily: font.body,
    fontWeight: 600,
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    cursor: "pointer",
    border: "none",
    borderBottom: `2px solid ${active ? palette.amber : "transparent"}`,
    background: "transparent",
    color: active ? palette.amber : palette.textMuted,
  });

  return (
    <div>
      <div style={{
        display: "flex",
        justifyContent: "center",
        gap: 8,
        background: palette.surface,
        borderBottom: `1px solid ${palette.border}`,
      }}>
        <button style={tabStyle(tab === "scanner")} onClick={() => setTab("scanner")}>
          Scanner
        </button>
        <button style={tabStyle(tab === "pdf_demo")} onClick={() => setTab("pdf_demo")}>
          PDF Demo
        </button>
      </div>
      {tab === "scanner" ? <DocScanner /> : <PdfDemo />}
    </div>
  );
}
