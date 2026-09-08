import { palette } from "../theme.js";

const COLORS = {
  green: palette.success,
  red: palette.danger,
  yellow: palette.warning,
  gray: palette.neutral,
};

/* status: "green" | "red" | "yellow" | "gray" */
export default function StatusDot({ status = "gray", label, title }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }} title={title}>
      <span
        style={{
          width: 9,
          height: 9,
          borderRadius: "50%",
          background: COLORS[status] || COLORS.gray,
          flexShrink: 0,
        }}
      />
      {label && <span style={{ fontSize: 13, color: palette.text }}>{label}</span>}
    </span>
  );
}
