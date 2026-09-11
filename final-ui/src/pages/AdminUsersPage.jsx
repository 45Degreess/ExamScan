import { useCallback, useEffect, useState } from "react";
import { createStaff, emailStaffPassword, listStaff, updateStaff } from "../api/auth.js";
import Button from "../components/Button.jsx";
import Card from "../components/Card.jsx";
import DataTable from "../components/DataTable.jsx";
import FormField, { TextInput } from "../components/FormField.jsx";
import { font, palette, radius, space } from "../theme.js";

const selectStyle = {
  width: "100%",
  padding: "9px 12px",
  borderRadius: radius.sm,
  border: `1px solid ${palette.borderStrong}`,
  background: palette.surface,
  color: palette.text,
  fontFamily: font.body,
  fontSize: 13.5,
};

export default function AdminUsersPage() {
  const [users, setUsers] = useState([]);
  const [editing, setEditing] = useState(null);
  const [newUser, setNewUser] = useState({ uct_id: "", name: "", email: "", role: "operator" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const reload = useCallback(async () => setUsers(await listStaff()), []);
  useEffect(() => { reload().catch((err) => setError(err.message)); }, [reload]);

  const run = async (action, successMessage) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      await reload();
      setMessage(successMessage);
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const addUser = async (event) => {
    event.preventDefault();
    let deliverySent = false;
    const saved = await run(async () => {
      const result = await createStaff(newUser);
      deliverySent = result.password_email_sent;
    }, "Staff account created.");
    if (saved) {
      setNewUser({ uct_id: "", name: "", email: "", role: "operator" });
      setMessage(deliverySent ? "Staff account created and password emailed." : "Staff account created, but the password email failed. Use Send password to retry.");
    }
  };

  const saveEdit = async (event) => {
    event.preventDefault();
    const saved = await run(
      () => updateStaff(editing.id, { name: editing.name, email: editing.email, role: editing.role, active: editing.active }),
      "Staff account updated.",
    );
    if (saved) setEditing(null);
  };

  const columns = [
    { key: "uct_id", header: "UCT ID" },
    { key: "name", header: "Name" },
    { key: "email", header: "Email" },
    { key: "role", header: "Role" },
    { key: "status", header: "Status", render: (row) => row.active ? "Active" : "Inactive" },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div style={{ display: "flex", gap: space.xs, flexWrap: "wrap" }}>
          <Button variant="subtle" disabled={busy} onClick={() => setEditing({ ...row })}>Edit</Button>
          <Button disabled={busy || !row.active} onClick={() => run(() => emailStaffPassword(row.id), "A new password has been emailed.")}>Send password</Button>
        </div>
      ),
    },
  ];

  return (
    <main style={{ padding: `${space.xl}px ${space.lg}px`, fontFamily: font.body, color: palette.text }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <h1 style={{ marginTop: 0, fontSize: 28 }}>Staff accounts</h1>
        <p style={{ color: palette.textMuted, fontSize: 13.5 }}>
          Staff receive a random password by email. Deactivating an account signs it out everywhere.
        </p>

        {error && <p role="alert" style={{ color: palette.danger }}>{error}</p>}
        {message && <p role="status" style={{ color: palette.success }}>{message}</p>}

        <div style={{ display: "flex", flexWrap: "wrap", gap: space.lg, alignItems: "start" }}>
          <Card title="Add staff member" subtitle="The initial password is emailed immediately." style={{ flex: "1 1 280px" }}>
            <form onSubmit={addUser}>
              <FormField label="UCT ID"><TextInput required value={newUser.uct_id} onChange={(event) => setNewUser({ ...newUser, uct_id: event.target.value.toUpperCase() })} /></FormField>
              <FormField label="Full name"><TextInput required value={newUser.name} onChange={(event) => setNewUser({ ...newUser, name: event.target.value })} /></FormField>
              <FormField label="Email"><TextInput required type="email" value={newUser.email} onChange={(event) => setNewUser({ ...newUser, email: event.target.value })} /></FormField>
              <FormField label="Role">
                <select style={selectStyle} value={newUser.role} onChange={(event) => setNewUser({ ...newUser, role: event.target.value })}>
                  <option value="operator">Operator</option>
                  <option value="admin">Administrator</option>
                </select>
              </FormField>
              <Button type="submit" variant="primary" disabled={busy}>Add and email password</Button>
            </form>
          </Card>

          <Card title="Registered staff" style={{ flex: "2 1 540px", minWidth: 0 }}>
            <DataTable columns={columns} rows={users} emptyText="No staff accounts exist." maxHeight={600} rowStyle={(row) => !row.active ? { opacity: 0.6 } : null} />
          </Card>
        </div>

        {editing && (
          <div style={{ marginTop: space.lg, maxWidth: 520 }}>
            <Card title={`Edit ${editing.uct_id}`}>
              <form onSubmit={saveEdit}>
                <FormField label="Full name"><TextInput required value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /></FormField>
                <FormField label="Email"><TextInput required type="email" value={editing.email} onChange={(event) => setEditing({ ...editing, email: event.target.value })} /></FormField>
                <FormField label="Role">
                  <select style={selectStyle} value={editing.role} onChange={(event) => setEditing({ ...editing, role: event.target.value })}>
                    <option value="operator">Operator</option>
                    <option value="admin">Administrator</option>
                  </select>
                </FormField>
                <label style={{ display: "flex", gap: space.sm, alignItems: "center", marginBottom: space.md }}>
                  <input type="checkbox" checked={editing.active} onChange={(event) => setEditing({ ...editing, active: event.target.checked })} />
                  Active account
                </label>
                <div style={{ display: "flex", gap: space.sm }}>
                  <Button type="submit" variant="primary" disabled={busy}>Save changes</Button>
                  <Button disabled={busy} onClick={() => setEditing(null)}>Cancel</Button>
                </div>
              </form>
            </Card>
          </div>
        )}
      </div>
    </main>
  );
}
