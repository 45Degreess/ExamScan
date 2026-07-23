import { useState, useRef, useCallback } from "react";
import { palette, font, grainUrl, Btn, Label } from "./theme.jsx";

const API_BASE = "/api";

/* Recursively walk a dropped FileSystemEntry tree, flattening to a File[] list. */
async function collectFilesFromEntry(entry, out) {
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    out.push(file);
  } else if (entry.isDirectory) {
    const reader = entry.createReader();
    const entries = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    for (const child of entries) {
      await collectFilesFromEntry(child, out);
    }
  }
}

export default function PdfDemo() {
  const [folderPath, setFolderPath] = useState("");
  const [enhance, setEnhance] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const [loadingPath, setLoadingPath] = useState(false);
  const [loadingUpload, setLoadingUpload] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const folderInputRef = useRef(null);

  const processFolderUpload = useCallback(async (fileList) => {
    if (!fileList || fileList.length === 0) return;
    setLoadingUpload(true);
    setError(null);
    try {
      const fd = new FormData();
      for (const f of fileList) fd.append("files", f, f.name);
      fd.append("enhance", String(enhance));
      const res = await fetch(`${API_BASE}/process-folder`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Processing failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "exam_output.zip";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingUpload(false);
    }
  }, [enhance]);

  const processFolderPath = async () => {
    if (!folderPath.trim()) return;
    setLoadingPath(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("folder_path", folderPath.trim());
      fd.append("enhance", String(enhance));
      const res = await fetch(`${API_BASE}/process-folder`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Processing failed");
      }
      const data = await res.json();
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingPath(false);
    }
  };

  const onDrop = useCallback(async (e) => {
    e.preventDefault();
    setDragOver(false);
    const items = e.dataTransfer?.items;
    if (!items || items.length === 0) return;
    const collected = [];
    for (const item of items) {
      const entry = item.webkitGetAsEntry?.();
      if (entry) await collectFilesFromEntry(entry, collected);
    }
    processFolderUpload(collected);
  }, [processFolderUpload]);

  const reset = () => {
    setResult(null);
    setError(null);
    setFolderPath("");
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: palette.bg,
      backgroundImage: grainUrl,
      backgroundSize: "200px 200px",
      fontFamily: font.body,
      color: palette.text,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      padding: "40px 20px",
    }}>
      <header style={{ textAlign: "center", marginBottom: 48 }}>
        <h1 style={{
          fontFamily: font.display,
          fontSize: 32,
          fontWeight: 400,
          letterSpacing: "0.02em",
          margin: 0,
        }}>PDF Demo</h1>
        <p style={{
          color: palette.textMuted,
          fontSize: 12,
          letterSpacing: "0.15em",
          textTransform: "uppercase",
          margin: "8px 0 0",
        }}>Batch-process a folder of exam script photos</p>
      </header>

      <div style={{
        width: "100%",
        maxWidth: 720,
        background: palette.surface,
        border: `1px solid ${palette.border}`,
        borderRadius: 16,
        overflow: "hidden",
        padding: 24,
      }}>
        {/* Path input mode */}
        <Label>Server Folder Path</Label>
        <p style={{ fontSize: 12, color: palette.textMuted, marginTop: 0 }}>
          Output (student_info.txt + combined.pdf + page images) is written inside this folder.
        </p>
        <div style={{ display: "flex", gap: 10, marginBottom: 28 }}>
          <input
            type="text"
            value={folderPath}
            onChange={(e) => setFolderPath(e.target.value)}
            placeholder="/absolute/path/to/exam/folder"
            style={{
              flex: 1,
              padding: "10px 12px",
              borderRadius: 8,
              border: `1px solid ${palette.border}`,
              background: palette.bg,
              color: palette.text,
              fontFamily: font.body,
              fontSize: 13,
            }}
          />
          <Btn primary disabled={loadingPath || !folderPath.trim()} onClick={processFolderPath}>
            {loadingPath ? "⏳ Processing…" : "⚡ Process Folder"}
          </Btn>
        </div>

        {/* Upload / drag-drop mode */}
        <Label>Or Drop / Browse a Folder</Label>
        <p style={{ fontSize: 12, color: palette.textMuted, marginTop: 0 }}>
          Files are uploaded to the server; the result comes back as a ZIP download.
        </p>
        <div
          onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onClick={() => folderInputRef.current?.click()}
          style={{
            padding: "40px 20px",
            textAlign: "center",
            cursor: "pointer",
            border: `2px dashed ${dragOver ? palette.amber : palette.border}`,
            borderRadius: 12,
            marginBottom: 20,
            transition: "all 0.3s ease",
            background: dragOver ? palette.amberMuted : "transparent",
          }}
        >
          <input
            ref={folderInputRef}
            type="file"
            webkitdirectory="true"
            directory=""
            multiple
            style={{ display: "none" }}
            onChange={(e) => processFolderUpload(Array.from(e.target.files || []))}
          />
          <div style={{ fontSize: 36, marginBottom: 12, opacity: 0.6 }}>📁</div>
          <p style={{ fontSize: 14, margin: 0 }}>
            {loadingUpload
              ? "⏳ Uploading & processing…"
              : <>Drop a folder here or <span style={{ color: palette.amber, textDecoration: "underline" }}>browse</span></>}
          </p>
        </div>

        {/* Enhance toggle */}
        <div
          onClick={() => setEnhance(!enhance)}
          style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", userSelect: "none", marginBottom: 20 }}
        >
          <div style={{
            width: 40, height: 22, borderRadius: 11,
            background: enhance ? palette.amber : palette.border,
            position: "relative",
            transition: "background 0.2s",
          }}>
            <div style={{
              width: 16, height: 16, borderRadius: 8,
              background: "#fff",
              position: "absolute", top: 3,
              left: enhance ? 21 : 3,
              transition: "left 0.2s",
              boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
            }} />
          </div>
          <span style={{ fontSize: 13 }}>High-contrast enhancement</span>
        </div>

        {/* Result (path mode) */}
        {result && (
          <div style={{ marginTop: 8 }}>
            <Label>Result</Label>
            <div style={{
              border: `1px solid ${palette.border}`,
              borderRadius: 10,
              padding: 16,
              fontSize: 13,
              display: "flex",
              flexDirection: "column",
              gap: 6,
            }}>
              <div><strong style={{ color: palette.amber }}>Output folder:</strong> {result.output_dir}</div>
              <div><strong style={{ color: palette.amber }}>Pages processed:</strong> {result.num_pages}</div>
              <div><strong style={{ color: palette.amber }}>PDF:</strong> {result.pdf_filename}</div>
              <div style={{ marginTop: 8 }}>
                <strong style={{ color: palette.amber }}>Student info:</strong>
                {Object.keys(result.student_info || {}).length === 0 ? (
                  <div style={{ color: palette.textMuted, fontStyle: "italic" }}>No cover page detected.</div>
                ) : (
                  <div style={{ marginTop: 6 }}>
                    {Object.entries(result.student_info).map(([k, v]) => (
                      <div key={k}>
                        <span style={{ color: palette.textMuted }}>{k}:</span> {v || "—"}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div style={{ marginTop: 16 }}>
              <Btn onClick={reset} danger>✕ Reset</Btn>
            </div>
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div style={{
            marginTop: 16,
            padding: "12px 16px",
            background: palette.dangerBg,
            border: `1px solid ${palette.danger}`,
            borderRadius: 8,
            fontSize: 13,
            color: palette.danger,
          }}>
            ⚠ {error}
          </div>
        )}
      </div>
    </div>
  );
}
