"""
Build one self-contained contact_sheet.html from a batch-eval results.csv
and its per-script image folders (see ../batch_eval_cover_pages.py). Opens
directly in a browser via file:// — every image is embedded as a base64
data URI, no server, no build step.

Per script card: predicted fields with confidence badges (colour tiers
mirror final-ui/src/pages/DebugPage.jsx's confidenceCell), thumbnails
(click to enlarge), and four grading checkboxes that persist to
localStorage and export back into a filled-in results.csv.

Usage: python3 build_contact_sheet.py
   (defaults assume you're running from software/, against
    ../batch_eval_results/{results.csv,out/} produced by
    batch_eval_cover_pages.py)
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import sys
from pathlib import Path

import cv2
import numpy as np

MIME_BY_SUFFIX = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def read_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="") as fh:
        return list(csv.DictReader(fh))


def encode_file_b64(path: Path) -> str:
    mime = MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def encode_preview_b64(jpg_path: Path, max_width: int) -> str:
    image = cv2.imread(str(jpg_path))
    if image is None:
        return ""
    h, w = image.shape[:2]
    if w > max_width:
        scale = max_width / w
        image = cv2.resize(image, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return ""
    data = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def find_mark_candidates(folder: Path) -> list[Path]:
    return sorted(folder.glob("mark_candidate_*.png"))


def confidence_badge(value: str) -> str:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return '<span class="badge badge-na">—</span>'
    pct = round(c * 100)
    tier = "green" if c >= 0.8 else "yellow" if c >= 0.5 else "red"
    return f'<span class="badge badge-{tier}">{pct}%</span>'


def parse_mark_candidates(raw: str) -> list[tuple[str, str]]:
    if not raw:
        return []
    pairs = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        value, _, conf = chunk.partition(":")
        pairs.append((value, conf))
    return pairs


def build_card_html(row: dict, images_dir: Path, shared_regions_b64: str, max_width: int, warnings: list[str]) -> str:
    script_id = row["script_id"]
    batch = row["batch"]
    folder = images_dir / batch / script_id

    preview_path = folder / "detect_preview.jpg"
    if preview_path.exists():
        preview_b64 = encode_preview_b64(preview_path, max_width)
    else:
        warnings.append(f"{script_id}: missing detect_preview.jpg")
        preview_b64 = ""

    emplid_crop_path = folder / "emplid_crop.png"
    if emplid_crop_path.exists():
        emplid_b64 = encode_file_b64(emplid_crop_path)
    else:
        warnings.append(f"{script_id}: missing emplid_crop.png")
        emplid_b64 = ""

    candidate_paths = find_mark_candidates(folder)

    thumbs = []
    if preview_b64:
        thumbs.append(("Detect preview", preview_b64))
    if shared_regions_b64:
        thumbs.append(("Regions used (fixed, same every script)", shared_regions_b64))
    if emplid_b64:
        thumbs.append(("Emplid digits", emplid_b64))
    for p in candidate_paths:
        thumbs.append((p.stem.replace("mark_candidate_", "cand "), encode_file_b64(p)))

    thumb_html = "".join(
        f'<figure class="thumb" onclick="openLightbox(this)">'
        f'<img src="{src}" alt="{html.escape(label)}" data-full="{src}">'
        f'<figcaption>{html.escape(label)}</figcaption></figure>'
        for label, src in thumbs
    )
    if not candidate_paths:
        thumb_html += '<p class="no-candidates">No mark candidates found.</p>'

    mark_candidates = parse_mark_candidates(row.get("mark_candidates", ""))
    mark_candidates_html = ", ".join(f"{html.escape(v)} ({confidence_badge(c)})" for v, c in mark_candidates) or "—"

    predicted_mark = row.get("predicted_mark") or "—"
    needs_review = row.get("mark_needs_review", "")

    extra_flags = []
    if row.get("error"):
        extra_flags.append(f'<div class="flag flag-error">error: {html.escape(row["error"])}</div>')
    if row.get("detect_preview_ok") not in ("True", "true", "1", True):
        extra_flags.append('<div class="flag flag-error">detect_preview_ok: False</div>')
    extra_flags_html = "".join(extra_flags)

    fields = [
        ("framing_correct", "Framing correct"),
        ("student_number_correct", "Student number correct"),
        ("course_code_correct", "Course code correct"),
        ("mark_correct", "Mark correct"),
    ]
    checkboxes_html = "".join(
        f'<label class="toggle"><input type="checkbox" data-field="{field}" '
        f'onchange="onToggle(\'{html.escape(script_id)}\', this)"> {label}</label>'
        for field, label in fields
    )

    return f"""
    <div class="card" data-script-id="{html.escape(script_id)}">
      <div class="card-header">
        <span class="script-id">{html.escape(script_id)}</span>
        <span class="pill">{html.escape(batch)}</span>
        <span class="pill">rig overlay: {html.escape(row.get("apply_rig_overlay_flag", ""))}</span>
      </div>
      {extra_flags_html}
      <table class="fields">
        <tr><td>Student number</td><td>{html.escape(row.get("emplid_pred", "") or "—")}</td><td>{confidence_badge(row.get("emplid_confidence", ""))}</td></tr>
        <tr><td>Course code</td><td>{html.escape(row.get("course_code_pred", "") or "—")}</td><td>{confidence_badge(row.get("course_code_confidence", ""))}</td></tr>
        <tr><td>Number of pages</td><td>{html.escape(row.get("num_pages_pred", "") or "—")}</td><td>{confidence_badge(row.get("num_pages_confidence", ""))}</td></tr>
        <tr><td>Mark candidates</td><td colspan="2">{mark_candidates_html}</td></tr>
        <tr><td>Predicted mark</td><td colspan="2"><strong>{html.escape(str(predicted_mark))}</strong>{' <span class="flag-inline">needs review</span>' if needs_review in ("True", "true", True) else ""}</td></tr>
      </table>
      <div class="thumbs">{thumb_html}</div>
      <div class="toggles">{checkboxes_html}</div>
    </div>
    """


PAGE_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Contact Sheet</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #f4f4f5; margin: 0; padding: 24px; color: #1f2328; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .topbar {{ position: sticky; top: 0; background: #f4f4f5; padding: 8px 0 16px; display: flex; align-items: center; justify-content: space-between; z-index: 10; }}
  .stats {{ color: #6b7280; font-size: 13px; }}
  button.export {{ background: #16a34a; color: white; border: none; border-radius: 6px; padding: 10px 18px; font-size: 14px; cursor: pointer; }}
  button.export:hover {{ background: #128a3e; }}
  h2.section {{ font-size: 16px; margin: 28px 0 12px; color: #374151; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }}
  .card {{ background: white; border-radius: 10px; padding: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .card-header {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }}
  .script-id {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 600; font-size: 13px; }}
  .pill {{ background: #eef2ff; color: #4338ca; border-radius: 999px; padding: 2px 8px; font-size: 11px; }}
  .flag {{ border-radius: 6px; padding: 6px 8px; font-size: 12px; margin-bottom: 8px; }}
  .flag-error {{ background: #fef2f2; color: #dc2626; }}
  .flag-inline {{ color: #d97706; font-size: 11px; margin-left: 6px; }}
  table.fields {{ width: 100%; font-size: 13px; border-collapse: collapse; margin-bottom: 10px; }}
  table.fields td {{ padding: 3px 4px; vertical-align: middle; }}
  table.fields td:first-child {{ color: #6b7280; width: 40%; }}
  .badge {{ display: inline-block; border-radius: 999px; padding: 1px 7px; font-size: 11px; color: white; }}
  .badge-green {{ background: #16a34a; }}
  .badge-yellow {{ background: #d97706; }}
  .badge-red {{ background: #dc2626; }}
  .badge-na {{ background: #9ca3af; }}
  .thumbs {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }}
  .thumb {{ margin: 0; cursor: pointer; text-align: center; width: 84px; }}
  .thumb img {{ width: 84px; height: 84px; object-fit: cover; border-radius: 6px; border: 1px solid #e5e7eb; display: block; }}
  .thumb figcaption {{ font-size: 10px; color: #6b7280; word-break: break-word; margin-top: 2px; }}
  .no-candidates {{ font-size: 12px; color: #9ca3af; margin: 4px 0; }}
  .toggles {{ display: flex; flex-wrap: wrap; gap: 10px; border-top: 1px solid #f0f0f0; padding-top: 8px; }}
  .toggle {{ font-size: 12px; display: flex; align-items: center; gap: 4px; cursor: pointer; }}
  #lightbox {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 100; align-items: center; justify-content: center; cursor: zoom-out; }}
  #lightbox img {{ max-width: 92vw; max-height: 92vh; border-radius: 6px; }}
</style>
</head>
<body>
  <div class="topbar">
    <div>
      <h1>Contact Sheet</h1>
      <div class="stats">{stats}</div>
    </div>
    <button class="export" onclick="exportCsv()">Export graded CSV</button>
  </div>

  {sections}

  <div id="lightbox" onclick="this.style.display='none'"><img id="lightbox-img" src=""></div>

  <script type="application/json" id="raw-rows">{rows_json}</script>
  <script type="application/json" id="fieldnames">{fieldnames_json}</script>
  <script>
    const STORAGE_KEY = "contact_sheet_grades";

    function loadGrades() {{
      try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {{}}; }}
      catch (e) {{ return {{}}; }}
    }}

    function saveGrades(grades) {{
      try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(grades)); }}
      catch (e) {{ console.error("localStorage write failed", e); }}
    }}

    function onToggle(scriptId, checkbox) {{
      const grades = loadGrades();
      grades[scriptId] = grades[scriptId] || {{}};
      grades[scriptId][checkbox.dataset.field] = checkbox.checked;
      saveGrades(grades);
    }}

    function restoreGrades() {{
      const grades = loadGrades();
      document.querySelectorAll(".card").forEach((card) => {{
        const scriptId = card.dataset.scriptId;
        const saved = grades[scriptId];
        if (!saved) return;
        card.querySelectorAll("input[type=checkbox]").forEach((cb) => {{
          if (saved[cb.dataset.field]) cb.checked = true;
        }});
      }});
    }}

    function openLightbox(figure) {{
      const img = figure.querySelector("img");
      document.getElementById("lightbox-img").src = img.dataset.full;
      document.getElementById("lightbox").style.display = "flex";
    }}

    function csvEscape(value) {{
      const s = String(value ?? "");
      if (/[",\\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
      return s;
    }}

    function exportCsv() {{
      const rows = JSON.parse(document.getElementById("raw-rows").textContent);
      const fieldnames = JSON.parse(document.getElementById("fieldnames").textContent);
      const grades = loadGrades();
      const gradeFields = ["framing_correct", "student_number_correct", "course_code_correct", "mark_correct"];

      const outRows = rows.map((row) => {{
        const copy = Object.assign({{}}, row);
        const saved = grades[row.script_id] || {{}};
        gradeFields.forEach((f) => {{
          copy[f] = saved[f] === true ? "TRUE" : (saved[f] === false ? "FALSE" : (copy[f] || ""));
        }});
        return copy;
      }});

      const lines = [fieldnames.map(csvEscape).join(",")];
      outRows.forEach((row) => {{
        lines.push(fieldnames.map((f) => csvEscape(row[f])).join(","));
      }});
      const csvText = lines.join("\\r\\n");

      const blob = new Blob([csvText], {{ type: "text/csv" }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "results_graded.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }}

    restoreGrades();
  </script>
</body>
</html>
"""


def render_html(rows: list[dict], images_dir: Path, shared_regions_b64: str, max_width: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    batches: dict[str, list[dict]] = {}
    for row in rows:
        batches.setdefault(row["batch"], []).append(row)

    section_titles = {"batch1": "Batch 1 (rig)", "batch2": "Batch 2 (no rig)"}
    sections_html = []
    for batch_name, batch_rows in batches.items():
        title = section_titles.get(batch_name, batch_name)
        cards = "".join(
            build_card_html(row, images_dir, shared_regions_b64, max_width, warnings)
            for row in batch_rows
        )
        sections_html.append(f'<h2 class="section">{html.escape(title)} — {len(batch_rows)} scripts</h2><div class="grid">{cards}</div>')

    stats = " · ".join(f"{title}: {len(batches.get(name, []))}" for name, title in section_titles.items() if name in batches)
    other_batches = [n for n in batches if n not in section_titles]
    for n in other_batches:
        sections_html.append(f'<h2 class="section">{html.escape(n)} — {len(batches[n])} scripts</h2><div class="grid">{"".join(build_card_html(r, images_dir, shared_regions_b64, max_width, warnings) for r in batches[n])}</div>')

    fieldnames = list(rows[0].keys()) if rows else []
    page = PAGE_TEMPLATE.format(
        stats=html.escape(stats or f"{len(rows)} scripts"),
        sections="\n".join(sections_html),
        rows_json=json.dumps(rows),
        fieldnames_json=json.dumps(fieldnames),
    )
    return page, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-csv", default=Path("batch_eval_results/results.csv"), type=Path)
    parser.add_argument("--images-dir", default=Path("batch_eval_results/out"), type=Path)
    parser.add_argument("--output", default=Path("batch_eval_results/contact_sheet.html"), type=Path)
    parser.add_argument("--max-preview-width", type=int, default=1000)
    args = parser.parse_args()

    rows = read_rows(args.results_csv)
    print(f"Read {len(rows)} rows from {args.results_csv}")

    shared_regions_b64 = ""
    for row in rows:
        candidate = args.images_dir / row["batch"] / row["script_id"] / "regions_boxes.png"
        if candidate.exists():
            shared_regions_b64 = encode_file_b64(candidate)
            break
    if not shared_regions_b64:
        print("WARNING: no regions_boxes.png found anywhere, skipping shared regions thumbnail", file=sys.stderr)

    page, warnings = render_html(rows, args.images_dir, shared_regions_b64, args.max_preview_width)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    args.output.write_text(page, encoding="utf-8")
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
