import { useState } from "react";
import { palette, radius, font } from "../theme.js";

export default function Button({ children, variant = "default", disabled, onClick, type = "button", style: s, title }) {
  const [hovered, setHovered] = useState(false);

  const base = {
    padding: "9px 16px",
    borderRadius: radius.sm,
    border: "1px solid",
    fontSize: 13.5,
    fontFamily: font.body,
    fontWeight: 500,
    cursor: disabled ? "not-allowed" : "pointer",
    transition: "background 0.15s, border-color 0.15s",
    opacity: disabled ? 0.5 : 1,
    whiteSpace: "nowrap",
  };

  const variants = {
    primary: {
      background: hovered && !disabled ? palette.primaryHover : palette.primary,
      borderColor: palette.primary,
      color: "#fff",
    },
    default: {
      background: hovered && !disabled ? palette.bg : palette.surface,
      borderColor: palette.borderStrong,
      color: palette.text,
    },
    danger: {
      background: hovered && !disabled ? palette.dangerBg : "transparent",
      borderColor: palette.danger,
      color: palette.danger,
    },
    subtle: {
      background: hovered && !disabled ? palette.bg : "transparent",
      borderColor: "transparent",
      color: palette.textMuted,
    },
  };

  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ ...base, ...variants[variant], ...s }}
    >
      {children}
    </button>
  );
}
