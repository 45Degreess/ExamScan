"""
Run a batch of single cover-page images through the debug routes
(/detect-preview and /extract-booklet) over real HTTP, save per-script
debug artifacts, and write one results.csv for manual scoring.

Two input batches:
  --batch1-dir: a folder of subfolders, one cover-page image per subfolder
                (subfolder name = script id). Captured WITH the rig.
  --batch2-dir: a flat folder of cover-page images, one per script
                (filename stem = script id). Captured WITHOUT the rig.

Auth mirrors `make login` (see ../Makefile, ../scripts/extract_csrf.py):
POST /auth/login, keep the session cookie, read csrf_token from the JSON
response, send it as X-CSRF-Token on every POST.

Usage:
  python3 batch_eval_cover_pages.py --uct-id MSTDEV001 --password ... \
      --batch1-dir /path/to/rig_scripts --batch2-dir /path/to/no_rig_scripts \
      --output-dir ./batch_eval_out --csv-path ./results.csv
"""
from __future__ import annotations

import argparse
import base64
import csv
import sys
from pathlib import Path

import cv2
import numpy as np
import requests

_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def login(session: requests.Session, base_url: str, uct_id: str, password: str) -> str:
    resp = session.post(f"{base_url}/auth/login", json={"uct_id": uct_id, "password": password})
    body = resp.json()
    token = body.get("csrf_token")
    if not token:
        print(f"Login failed: {body}", file=sys.stderr)
        sys.exit(1)
    return token


def resolve_mark(candidates: list[int], test_total: int | None) -> tuple[int | None, bool]:
    """Verbatim port of _resolve_mark, software/routes.py:152-178."""
    if not candidates or test_total is None:
        return None, True
    c1 = candidates[0]
    c2 = candidates[1] if len(candidates) > 1 else None
    if c1 != test_total:
        return None, True
    if c2 is None or c2 == c1:
        return c1, False
    return c2, False


def find_batch1_images(batch1_dir: Path) -> list[tuple[str, Path]]:
    results = []
    for sub in sorted(p for p in batch1_dir.iterdir() if p.is_dir()):
        images = sorted(f for f in sub.iterdir() if f.is_file() and f.suffix.lower() in _IMAGE_EXTS)
        if not images:
            print(f"  WARNING: no image found in {sub}, skipping", file=sys.stderr)
            continue
        if len(images) > 1:
            print(f"  WARNING: {sub} has {len(images)} images, using {images[0].name}", file=sys.stderr)
        results.append((sub.name, images[0]))
    return results


def find_batch2_images(batch2_dir: Path) -> list[tuple[str, Path]]:
    images = sorted(f for f in batch2_dir.iterdir() if f.is_file() and f.suffix.lower() in _IMAGE_EXTS)
    return [(f.stem, f) for f in images]


def call_detect_preview(session, base_url, csrf, image_path: Path, apply_rig_overlay_flag: bool) -> bytes:
    with open(image_path, "rb") as fh:
        resp = session.post(
            f"{base_url}/detect-preview",
            headers={"X-CSRF-Token": csrf},
            files={"file": (image_path.name, fh, "image/jpeg")},
            data={"method": "colour", "apply_rig_overlay_flag": str(apply_rig_overlay_flag).lower()},
        )
    resp.raise_for_status()
    return resp.content


def call_extract_booklet(session, base_url, csrf, image_path: Path, apply_rig_overlay_flag: bool) -> dict:
    with open(image_path, "rb") as fh:
        resp = session.post(
            f"{base_url}/extract-booklet",
            headers={"X-CSRF-Token": csrf},
            files={"file": (image_path.name, fh, "image/jpeg")},
            data={"method": "colour", "apply_rig_overlay_flag": str(apply_rig_overlay_flag).lower()},
        )
    resp.raise_for_status()
    return resp.json()


def _decode_b64_png(b64_str: str) -> np.ndarray | None:
    if not b64_str:
        return None
    raw = base64.b64decode(b64_str)
    arr = np.frombuffer(raw, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)


def _draw_regions_boxes(scan_dimensions: dict, regions_used: dict) -> np.ndarray:
    width = scan_dimensions.get("width", 2480)
    height = scan_dimensions.get("height", 3508)
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    for field, box in regions_used.items():
        x, y, w, h = box
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 0, 220), 4)
        cv2.putText(canvas, field, (x, max(y - 12, 20)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 220), 3)
    return canvas


def save_artifacts(output_dir: Path, batch: str, script_id: str, preview_bytes: bytes, cover: dict, mark: dict) -> None:
    script_dir = output_dir / batch / script_id
    script_dir.mkdir(parents=True, exist_ok=True)

    (script_dir / "detect_preview.jpg").write_bytes(preview_bytes)

    if cover and "error" not in cover:
        emplid_img = _decode_b64_png(cover.get("crops", {}).get("Emplid", ""))
        if emplid_img is not None:
            cv2.imwrite(str(script_dir / "emplid_crop.png"), emplid_img)

        regions_used = cover.get("regions_used")
        scan_dimensions = cover.get("scan_dimensions")
        if regions_used and scan_dimensions:
            boxes_img = _draw_regions_boxes(scan_dimensions, regions_used)
            cv2.imwrite(str(script_dir / "regions_boxes.png"), boxes_img)

    if mark and "error" not in mark:
        for i, cand in enumerate(mark.get("candidates", [])):
            crop_img = _decode_b64_png(cand.get("crop", ""))
            if crop_img is not None:
                fname = f"mark_candidate_{i:02d}_region{cand.get('region_index')}_value{cand.get('value')}.png"
                cv2.imwrite(str(script_dir / fname), crop_img)


def process_script(session, base_url, csrf, output_dir, batch, script_id, image_path, apply_rig_overlay_flag, test_total) -> dict:
    row = {
        "script_id": script_id,
        "batch": batch,
        "apply_rig_overlay_flag": apply_rig_overlay_flag,
        "detect_preview_ok": False,
        "emplid_pred": "", "emplid_confidence": "",
        "course_code_pred": "", "course_code_confidence": "",
        "num_pages_pred": "", "num_pages_confidence": "",
        "mark_candidates": "",
        "predicted_mark": "", "mark_needs_review": "",
        "error": "",
        "framing_correct": "", "student_number_correct": "", "course_code_correct": "", "mark_correct": "",
    }
    try:
        preview_bytes = call_detect_preview(session, base_url, csrf, image_path, apply_rig_overlay_flag)
        row["detect_preview_ok"] = True

        result = call_extract_booklet(session, base_url, csrf, image_path, apply_rig_overlay_flag)
        cover = result.get("cover") or {}
        mark = result.get("mark") or {}

        save_artifacts(output_dir, batch, script_id, preview_bytes, cover, mark)

        if "error" in cover:
            row["error"] = f"cover: {cover['error']}"
        else:
            fields = cover.get("fields", {})
            confidences = cover.get("confidences", {})
            row["emplid_pred"] = fields.get("Emplid", "")
            row["emplid_confidence"] = confidences.get("Emplid", "")
            row["course_code_pred"] = fields.get("Course Code", "")
            row["course_code_confidence"] = confidences.get("Course Code", "")
            row["num_pages_pred"] = fields.get("number of pages", "")
            row["num_pages_confidence"] = confidences.get("number of pages", "")

        if "error" in mark:
            row["error"] = (row["error"] + f"; mark: {mark['error']}").strip("; ")
        else:
            candidates = mark.get("candidates", [])
            row["mark_candidates"] = ";".join(f"{c['value']}:{c['confidence']:.3f}" for c in candidates)
            top_values = [c["value"] for c in candidates][:2]
            predicted_mark, needs_review = resolve_mark(top_values, test_total)
            row["predicted_mark"] = predicted_mark if predicted_mark is not None else ""
            row["mark_needs_review"] = needs_review

    except Exception as exc:
        row["error"] = (row["error"] + f"; {exc}").strip("; ")

    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uct-id", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--batch1-dir", required=True, type=Path, help="rig-captured: one subfolder per script")
    parser.add_argument("--batch2-dir", required=True, type=Path, help="non-rig: flat folder of images")
    parser.add_argument("--test-total", type=int, default=35)
    parser.add_argument("--output-dir", default=Path("./batch_eval_out"), type=Path)
    parser.add_argument("--csv-path", default=Path("./results.csv"), type=Path)
    args = parser.parse_args()

    session = requests.Session()
    csrf = login(session, args.base_url, args.uct_id, args.password)
    print("Logged in.")

    batch1_scripts = find_batch1_images(args.batch1_dir)
    batch2_scripts = find_batch2_images(args.batch2_dir)
    print(f"Batch 1 (rig): {len(batch1_scripts)} scripts. Batch 2 (no rig): {len(batch2_scripts)} scripts.")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "script_id", "batch", "apply_rig_overlay_flag",
        "detect_preview_ok",
        "emplid_pred", "emplid_confidence",
        "course_code_pred", "course_code_confidence",
        "num_pages_pred", "num_pages_confidence",
        "mark_candidates",
        "predicted_mark", "mark_needs_review",
        "error",
        "framing_correct", "student_number_correct", "course_code_correct", "mark_correct",
    ]

    with open(args.csv_path, "w", newline="") as csv_fh:
        writer = csv.DictWriter(csv_fh, fieldnames=fieldnames)
        writer.writeheader()

        for batch_name, scripts, overlay_flag in (
            ("batch1", batch1_scripts, True),
            ("batch2", batch2_scripts, False),
        ):
            for script_id, image_path in scripts:
                print(f"[{batch_name}] {script_id} ({image_path.name})...")
                row = process_script(
                    session, args.base_url, csrf, args.output_dir,
                    batch_name, script_id, image_path, overlay_flag, args.test_total,
                )
                if row["error"]:
                    print(f"  ERROR: {row['error']}", file=sys.stderr)
                writer.writerow(row)
                csv_fh.flush()

    print(f"Done. Results: {args.csv_path}  Artifacts: {args.output_dir}")


if __name__ == "__main__":
    main()
