import { palette } from "../theme.js";

/* columns: [{ key, header, render?: (row) => node }]
   rowStyle?: (row) => style object, merged onto that row's <tr> */
export default function DataTable({ columns, rows, emptyText = "Nothing to show yet.", maxHeight = 480, rowStyle }) {
  if (!rows.length) {
    return (
      <div style={{ padding: "32px 16px", textAlign: "center", color: palette.textMuted, fontSize: 13 }}>
        {emptyText}
      </div>
    );
  }

  return (
    <div style={{ maxHeight, overflowY: "auto", border: `1px solid ${palette.border}`, borderRadius: 10 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ position: "sticky", top: 0, background: palette.bg, zIndex: 1 }}>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
                  textAlign: "left",
                  padding: "10px 14px",
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: palette.textMuted,
                  borderBottom: `1px solid ${palette.border}`,
                }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.id ?? i}
              style={{
                borderBottom: i < rows.length - 1 ? `1px solid ${palette.border}` : "none",
                ...(rowStyle ? rowStyle(row) : null),
              }}
            >
              {columns.map((col) => (
                <td key={col.key} style={{ padding: "10px 14px", color: palette.text, verticalAlign: "middle" }}>
                  {col.render ? col.render(row) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
