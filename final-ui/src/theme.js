/*
 * final-ui theme — light, minimal, operator-facing.
 * Deliberately plain: no gradients/textures/mono-font branding like the old
 * "darkroom" theme in examscan-ui/src/theme.jsx. Optimised for a non-technical
 * user scanning quickly through forms and a status table.
 */

export const palette = {
  bg: "#f6f7f9",
  surface: "#ffffff",
  border: "#e2e5ea",
  borderStrong: "#c9ced6",
  text: "#1c2027",
  textMuted: "#6b7280",
  primary: "#2563eb",
  primaryHover: "#1d4ed8",
  primaryMuted: "rgba(37,99,235,0.08)",
  danger: "#dc2626",
  dangerBg: "rgba(220,38,38,0.08)",
  success: "#16a34a",
  successBg: "rgba(22,163,74,0.1)",
  warning: "#d97706",
  warningBg: "rgba(217,119,6,0.1)",
  neutral: "#9ca3af",
  neutralBg: "rgba(156,163,175,0.15)",
};

export const font = {
  body: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
};

export const space = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 40,
};

export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
};
