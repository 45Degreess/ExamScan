import { palette, radius, font, space } from "../theme.js";

export default function FormField({ label, children }) {
  return (
    <label style={{ display: "block", marginBottom: space.md }}>
      <span style={{ display: "block", fontSize: 12.5, fontWeight: 600, color: palette.textMuted, marginBottom: 6 }}>
        {label}
      </span>
      {children}
    </label>
  );
}

const inputStyle = {
  width: "100%",
  boxSizing: "border-box",
  padding: "9px 12px",
  borderRadius: radius.sm,
  border: `1px solid ${palette.borderStrong}`,
  background: palette.surface,
  color: palette.text,
  fontFamily: font.body,
  fontSize: 13.5,
};

export function TextInput(props) {
  return <input {...props} style={{ ...inputStyle, ...(props.style || {}) }} />;
}
