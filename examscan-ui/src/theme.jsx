import { useState } from "react";

/*
 * Shared "Darkroom" theme — matte black + amber accents + film-grain texture.
 * Used by DocScanner.jsx and PdfDemo.jsx.
 */

export const palette = {
  bg: "#0e0e10",
  surface: "#18181c",
  surfaceHover: "#222228",
  border: "#2a2a30",
  borderFocus: "#d4a054",
  amber: "#d4a054",
  amberMuted: "rgba(212,160,84,0.12)",
  amberGlow: "rgba(212,160,84,0.35)",
  text: "#e8e4de",
  textMuted: "#8a8680",
  danger: "#c44d56",
  dangerBg: "rgba(196,77,86,0.1)",
  success: "#5cb87a",
  successBg: "rgba(92,184,122,0.08)",
};

export const font = {
  display: "'DM Serif Display', 'Georgia', serif",
  body: "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
};

const grainSvg = `<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.04'/></svg>`;
export const grainUrl = `url("data:image/svg+xml,${encodeURIComponent(grainSvg)}")`;

export function Btn({ children, primary, danger, disabled, onClick, style: s }) {
  const [hovered, setHovered] = useState(false);
  const base = {
    padding: "10px 20px",
    borderRadius: 8,
    border: "1px solid",
    fontSize: 13,
    fontFamily: font.body,
    fontWeight: 500,
    cursor: disabled ? "not-allowed" : "pointer",
    transition: "all 0.2s",
    opacity: disabled ? 0.5 : 1,
    whiteSpace: "nowrap",
  };
  let colors;
  if (primary) {
    colors = {
      background: hovered ? palette.amber : "transparent",
      borderColor: palette.amber,
      color: hovered ? palette.bg : palette.amber,
    };
  } else if (danger) {
    colors = {
      background: hovered ? palette.dangerBg : "transparent",
      borderColor: palette.danger,
      color: palette.danger,
    };
  } else {
    colors = {
      background: hovered ? palette.surfaceHover : "transparent",
      borderColor: palette.border,
      color: palette.text,
    };
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ ...base, ...colors, ...s }}
    >
      {children}
    </button>
  );
}

export function Label({ children, style: s }) {
  return (
    <div style={{
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: "0.12em",
      textTransform: "uppercase",
      color: palette.textMuted,
      marginBottom: 8,
      ...s,
    }}>
      {children}
    </div>
  );
}

export function ImgFrame({ src, alt }) {
  return (
    <div style={{
      border: `1px solid ${palette.border}`,
      borderRadius: 10,
      overflow: "hidden",
      background: "#111",
      lineHeight: 0,
    }}>
      <img
        src={src}
        alt={alt}
        style={{
          width: "100%",
          display: "block",
          objectFit: "contain",
          maxHeight: 460,
        }}
      />
    </div>
  );
}
