import { useEffect, useState } from "react";
import { updateBooklet, getBookletCrops } from "../api/sessions.js";
import Button from "./Button.jsx";
import FormField, { TextInput } from "./FormField.jsx";
import { palette, space } from "../theme.js";

function CropThumb({ crop, alt }) {
  if (!crop) return null;
  return (
    <img
      src={`data:image/png;base64,${crop}`}
      alt={alt}
      style={{
        maxHeight: 34,
        maxWidth: 180,
        border: `1px solid ${palette.border}`,
        borderRadius: 4,
        imageRendering: "pixelated",
        flexShrink: 0,
      }}
    />
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
        // leaves the reference images/values off the form.
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
      <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: 16 }}>Edit booklet</h2>
      <FormField label="Emplid">
        <div style={{ display: "flex", gap: space.sm, alignItems: "center" }}>
          <TextInput
            value={emplid}
            onChange={(event) => setEmplid(event.target.value)}
            required
            style={{ flex: 1 }}
          />
          <CropThumb crop={crops?.emplid_crop} alt="Scanned Emplid" />
        </div>
      </FormField>
      <FormField label="Course code">
        <div style={{ display: "flex", gap: space.sm, alignItems: "center" }}>
          <TextInput
            value={courseCode}
            onChange={(event) => setCourseCode(event.target.value)}
            style={{ flex: 1 }}
          />
          <CropThumb crop={crops?.course_code_crop} alt="Scanned course code" />
        </div>
      </FormField>
      <FormField label="Number of pages">
        <TextInput type="number" min="1" value={numPages} onChange={(event) => setNumPages(event.target.value)} />
      </FormField>
      <FormField label="Mark">
        <div style={{ display: "flex", gap: space.sm, alignItems: "center" }}>
          <TextInput
            type="number"
            min="0"
            value={mark}
            onChange={(event) => setMark(event.target.value)}
            style={{ flex: 1 }}
          />
          {crops?.mark_candidates?.length > 0 && (
            <span style={{ fontSize: 12, color: palette.textMuted, whiteSpace: "nowrap" }}>
              Extracted: {crops.mark_candidates.join(", ")}
            </span>
          )}
        </div>
      </FormField>
      {error && <p role="alert" style={{ color: palette.danger, fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: space.sm }}>
        <Button type="submit" variant="primary" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
        <Button disabled={saving} onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
