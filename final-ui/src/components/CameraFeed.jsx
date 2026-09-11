import { useEffect, useState } from "react";
import { piStreamUrl } from "../api/sessions.js";
import { palette, space } from "../theme.js";

export default function CameraFeed() {
  const [attempt, setAttempt] = useState(0);
  const [online, setOnline] = useState(true);

  useEffect(() => {
    if (online) return undefined;
    const timer = window.setTimeout(() => {
      setAttempt((value) => value + 1);
      setOnline(true);
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [online]);

  return (
    <div style={{ width: "100%", minHeight: 180, display: "flex", alignItems: "center", justifyContent: "center", background: palette.neutralBg }}>
      {online ? (
        <img
          key={attempt}
          src={`${piStreamUrl()}?attempt=${attempt}`}
          alt="Live ExamScan camera preview"
          onError={() => setOnline(false)}
          style={{ display: "block", width: "100%", height: "100%", minHeight: 180, objectFit: "contain" }}
        />
      ) : (
        <p style={{ margin: space.md, color: palette.textMuted, fontSize: 13 }}>Reconnecting to the camera…</p>
      )}
    </div>
  );
}
