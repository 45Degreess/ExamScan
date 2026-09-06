import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { palette, space, font } from "../theme.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusDot from "../components/StatusDot.jsx";
import { TextInput } from "../components/FormField.jsx";
import { useSession } from "../context/SessionContext.jsx";
import { getSessionReview, finalizeSession, bookletPdfUrl } from "../api/sessions.js";

// Post-processing / review step. Sits after View Session. Pulls the merged
// review feed (roster rows + stray scanned booklets), ordered
// unexpected → missing → scanned → excluded, and lets the operator eyeball
// each one (open the PDF, read the OCR confidence) before closing the session
// off. "End session and confirm results" writes the final expected flags —
// roster rows left deselected become expected=0 — and marks the session
// finalized, in one request. Finalize is advisory only; the page stays usable.
//
// NOTE: deselecting a stray booklet row (status "unexpected", no `username`)
// has no persisted effect yet — a future "Edit" flow will re-identify those.

const STATUS_DOT = {
  unexpected: "red",
  missing: "yellow",
  scanned: "green",
  excluded: "gray",
};
const STATUS_LABEL = {
  unexpected: "Unexpected",
  missing: "Missing",
  scanned: "Scanned",
  excluded: "Excluded",
};

function confidenceCell(c) {
  if (c === null || c === undefined) {
    return <span style={{ color: palette.textMuted }}>—</span>;
  }
  const pct = Math.round(c * 100);
  const dot = c >= 0.8 ? "green" : c >= 0.5 ? "yellow" : "red";
  return <StatusDot status={dot} label={`${pct}%`} />;
}

export default function ReviewSessionPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { currentSession, loadSession } = useSession();

  const [session, setSession] = useState(null);
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [sessionStatus, setSessionStatus] = useState("open");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmArmed, setConfirmArmed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    let s = currentSession;
    if (!s || String(s.id) !== String(sessionId)) {
      s = loadSession(sessionId);
    }
    if (!s) {
      navigate("/");
      return;
    }
    setSession(s);

    if (!s.sessionCode) {
      setError("This session has no code on record — recreate it.");
      setLoading(false);
      return;
    }

    setLoading(true);
    getSessionReview(s.sessionCode)
      .then((data) => {
        if (cancelled) return;
        const rows = (data.items || []).map((it) => ({ ...it, id: it.row_key }));
        setItems(rows);
        setSessionStatus(data.session_status || "open");
        setSelected(
          new Set(
            rows
              .filter((r) => r.status === "scanned" || r.status === "excluded")
              .map((r) => r.id),
          ),
        );
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) =>
        (it.name || "").toLowerCase().includes(q) ||
        (it.emplid || "").toLowerCase().includes(q) ||
        (it.username || "").toLowerCase().includes(q),
    );
  }, [items, search]);

  const toggle = (rowKey) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(rowKey) ? next.delete(rowKey) : next.add(rowKey);
      return next;
    });
  };

  const handleFinalize = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const excluded = items
        .filter((it) => it.username && !selected.has(it.id))
        .map((it) => it.username);
      await finalizeSession(session.sessionCode, excluded);
      navigate("/");
    } catch (e) {
      setError(e.message);
      setSubmitting(false);
      setConfirmArmed(false);
    }
  };

  const columns = [
    { key: "name", header: "Name" },
    {
      key: "confidence",
      header: "Confidence",
      render: (row) => confidenceCell(row.confidence),
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <StatusDot status={STATUS_DOT[row.status] || "gray"} label={STATUS_LABEL[row.status] || row.status} />
      ),
    },
    {
      key: "view",
      header: "View",
      render: (row) => {
        const canView = row.booklet_id != null;
        return (
          <a
            href={canView ? bookletPdfUrl(session.sessionCode, row.booklet_id) : "#"}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => !canView && e.preventDefault()}
            style={{
              color: canView ? palette.primary : palette.neutral,
              pointerEvents: canView ? "auto" : "none",
              fontSize: 13,
              textDecoration: canView ? "underline" : "none",
            }}
            title={canView ? undefined : "No scan for this row"}
          >
            Open PDF
          </a>
        );
      },
    },
    {
      key: "edit",
      header: "Edit",
      render: () => (
        <Button
          variant="subtle"
          style={{ padding: "4px 12px" }}
          title="Not yet implemented"
          onClick={() => {}}
        >
          Edit
        </Button>
      ),
    },
    {
      key: "select",
      header: "",
      render: (row) => {
        const isSel = selected.has(row.id);
        return (
          <Button
            variant={isSel ? "primary" : "default"}
            style={{ padding: "4px 12px" }}
            onClick={() => toggle(row.id)}
            title={
              isSel
                ? "Selected — kept as-is. Click to deselect."
                : "Deselected — roster rows here are written expected=0 on confirm."
            }
          >
            {isSel ? "Selected" : "Deselected"}
          </Button>
        );
      },
    },
  ];

  const errorBox = error && (
    <div
      style={{
        marginBottom: space.md,
        padding: "10px 14px",
        background: palette.dangerBg,
        border: `1px solid ${palette.danger}`,
        borderRadius: 8,
        fontSize: 13,
        color: palette.danger,
      }}
    >
      {error}
    </div>
  );

  return (
    <div
      style={{
        minHeight: "100vh",
        background: palette.bg,
        fontFamily: font.body,
        color: palette.text,
        padding: space.lg,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: space.lg,
        }}
      >
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>
            Review &amp; Finalize{session?.sessionCode ? ` — ${session.sessionCode}` : ""}
          </h1>
          <p style={{ fontSize: 13, color: palette.textMuted, margin: "6px 0 0" }}>
            {selected.size} of {items.length} rows selected · deselected roster rows are
            written expected=0 on confirm.
          </p>
          {sessionStatus === "finalized" && (
            <p style={{ fontSize: 13, color: palette.textMuted, margin: "4px 0 0" }}>
              This session is already finalized. You can still adjust selections and re-confirm.
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: space.sm }}>
          <Button
            variant="subtle"
            disabled={submitting}
            onClick={() => navigate(`/sessions/${sessionId}`)}
          >
            ← Back to session
          </Button>
          <Button
            variant={confirmArmed ? "danger" : "primary"}
            disabled={loading || submitting}
            onClick={confirmArmed ? handleFinalize : () => setConfirmArmed(true)}
          >
            {submitting
              ? "Finalizing…"
              : confirmArmed
                ? "Confirm — locks the session"
                : "End session and confirm results"}
          </Button>
        </div>
      </div>

      <Card style={{ maxWidth: 900 }} title="Scripts & Students">
        {errorBox}

        {loading ? (
          <div style={{ padding: "32px 16px", textAlign: "center", color: palette.textMuted, fontSize: 13 }}>
            Loading review…
          </div>
        ) : (
          <>
            <TextInput
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or ID…"
              style={{ marginBottom: space.md }}
            />
            <DataTable
              columns={columns}
              rows={filtered}
              rowStyle={(row) => (selected.has(row.id) ? null : { opacity: 0.45 })}
              emptyText={
                items.length === 0
                  ? "Nothing to review yet."
                  : "No rows match your search."
              }
            />
          </>
        )}
      </Card>
    </div>
  );
}
