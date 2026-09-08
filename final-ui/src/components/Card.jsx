import { palette, radius, space } from "../theme.js";

export default function Card({ children, style: s, title, subtitle }) {
  return (
    <div
      style={{
        background: palette.surface,
        border: `1px solid ${palette.border}`,
        borderRadius: radius.lg,
        padding: space.lg,
        boxShadow: "0 1px 2px rgba(16,24,40,0.04)",
        ...s,
      }}
    >
      {title && (
        <div style={{ marginBottom: subtitle ? 2 : space.md }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: palette.text }}>{title}</h2>
        </div>
      )}
      {subtitle && (
        <p style={{ margin: `0 0 ${space.md}px`, fontSize: 12.5, color: palette.textMuted }}>{subtitle}</p>
      )}
      {children}
    </div>
  );
}
