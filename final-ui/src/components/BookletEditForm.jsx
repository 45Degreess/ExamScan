import { useEffect, useState } from "react";
import { updateBooklet, getBookletCrops } from "../api/sessions.js";
import Button from "./Button.jsx";
import FormField, { TextInput } from "./FormField.jsx";
import { palette, space } from "../theme.js";

const headerStyle = {
  fontSize: 11,
  fontWeight: 600,
  color: palette.textMuted,
  borderBottom: `1px solid ${palette.border}`,
  paddingBottom: 4,
  marginBottom: space.sm,
};

function ReferenceCell({ label, crop, note }) {
  return (
    <div>
      <span style={{ display: "block", fontSize: 11, color: palette.textMuted, marginBottom: 4 }}>
        {label}
      </span>
      {crop ? (
        <img
          src={`data:image/png;base64,${crop}`}
          alt={label}
          style={{
            maxHeight: 40,
            maxWidth: "100%",
            border: `1px solid ${palette.border}`,
            borderRadius: 4,
            imageRendering: "pixelated",
            display: "block",
          }}
        />
      ) : (
        <span style={{ fontSize: 12, color: palette.textMuted }}>{note || "—"}</span>
      )}
    </div>
  );
}

// Mark row's reference cell shows both extracted candidates, each with the
// ink crop it was read from (mark_candidates[i] pairs with mark_crop_<i+1>
// — same order they were pooled/ranked in on the backend).
function MarkReferenceCell({ candidates, crops }) {
  return (
    <div>
      <span style={{ display: "block", fontSize: 11, color: palette.textMuted, marginBottom: 4 }}>
        Extracted candidates
      </span>
      {candidates.length ? (
        <div style={{ display: "flex", gap: space.md }}>
          {candidates.map((value, i) => (
            <div key={i}>
              {crops[i] && (
                <img
                  src={`data:image/png;base64,${crops[i]}`}
                  alt={`Candidate ${value}`}
                  style={{
                    maxHeight: 40,
                    maxWidth: 110,
                    border: `1px solid ${palette.border}`,
                    borderRadius: 4,
                    imageRendering: "pixelated",
                    display: "block",
                    marginBottom: 2,
                  }}
                />
              )}
              <span style={{ fontSize: 11, color: palette.textMuted }}>{value}</span>
            </div>
          ))}
        </div>
      ) : (
        <span style={{ fontSize: 12, color: palette.textMuted }}>—</span>
      )}
    </div>
  );
}

export default function BookletEditForm({ sessionCode, booklet, onSaved, onCancel }) {
  const [emplid, setEmplid] = useState(booklet.emplid || "");
  const [courseCode, setCourseCode] = useState(booklet.courseCodeScanned || "");
  const [numPages, setNumPages] = useState(booklet.numPages ?? "");
  const [mark, setMark] = useState(booklet.mark ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [crops, setCrops] = useState(null); // { emplid_crop, course_code_crop, mark_candidates } once loaded

  useEffect(() => {
    let cancelled = false;
    getBookletCrops(sessionCode, booklet.id)
      .then((data) => {
        if (!cancelled) setCrops(data);
      })
      .catch(() => {
        // Crops are a nice-to-have for manual review; a failed fetch just
        // leaves the reference column blank.
      });
    return () => {
      cancelled = true;
    };
  }, [sessionCode, booklet.id]);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await updateBooklet(sessionCode, booklet.id, {
        emplid: emplid.trim(),
        courseCodeScanned: courseCode.trim(),
        numPages,
        mark,
      });
      onSaved();
    } catch (err) {
      setError(err.message || "The booklet could not be updated.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: space.lg, alignItems: "start" }}>
        <div style={headerStyle}>Field</div>
        <div style={headerStyle}>Scanned reference</div>

        <FormField label="Emplid">
          <TextInput value={emplid} onChange={(event) => setEmplid(event.target.value)} required />
        </FormField>
        <ReferenceCell label="Scanned Emplid" crop={crops?.emplid_crop} />

        <FormField label="Course code">
          <TextInput value={courseCode} onChange={(event) => setCourseCode(event.target.value)} />
        </FormField>
        <ReferenceCell label="Scanned course code" crop={crops?.course_code_crop} />

        <FormField label="Number of pages">
          <TextInput type="number" min="1" value={numPages} onChange={(event) => setNumPages(event.target.value)} />
        </FormField>
        <div />

        <FormField label="Mark">
          <TextInput type="number" min="0" value={mark} onChange={(event) => setMark(event.target.value)} />
        </FormField>
        <MarkReferenceCell
          candidates={crops?.mark_candidates || []}
          crops={[crops?.mark_crop_1, crops?.mark_crop_2]}
        />
      </div>
      {error && <p role="alert" style={{ color: palette.danger, fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: space.sm, marginTop: space.sm }}>
        <Button type="submit" variant="primary" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
        <Button disabled={saving} onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
