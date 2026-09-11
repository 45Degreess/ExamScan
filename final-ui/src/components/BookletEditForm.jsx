import { useState } from "react";
import { updateBooklet } from "../api/sessions.js";
import Button from "./Button.jsx";
import FormField, { TextInput } from "./FormField.jsx";
import { palette, space } from "../theme.js";

export default function BookletEditForm({ sessionCode, booklet, onSaved, onCancel }) {
  const [emplid, setEmplid] = useState(booklet.emplid || "");
  const [courseCode, setCourseCode] = useState(booklet.courseCodeScanned || "");
  const [numPages, setNumPages] = useState(booklet.numPages ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await updateBooklet(sessionCode, booklet.id, {
        emplid: emplid.trim(),
        courseCodeScanned: courseCode.trim(),
        numPages,
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
        <TextInput value={emplid} onChange={(event) => setEmplid(event.target.value)} required />
      </FormField>
      <FormField label="Course code">
        <TextInput value={courseCode} onChange={(event) => setCourseCode(event.target.value)} />
      </FormField>
      <FormField label="Number of pages">
        <TextInput type="number" min="1" value={numPages} onChange={(event) => setNumPages(event.target.value)} />
      </FormField>
      {error && <p role="alert" style={{ color: palette.danger, fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: space.sm }}>
        <Button type="submit" variant="primary" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
        <Button disabled={saving} onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
