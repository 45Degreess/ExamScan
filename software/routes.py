from __future__ import annotations

import csv
import io
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import cv2
import httpx
import numpy as np
from imutils.perspective import four_point_transform
from PIL import Image as PILImage
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi import Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

import db

SAMPLE_DIR = Path(__file__).parent / "sample_images"
STORAGE_ROOT = Path(__file__).parent / "storage"
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

from constants import (
    A4_WIDTH,
    A4_HEIGHT,
    A3_WIDTH,
    A3_HEIGHT,
    COVER_FIELDS,
    MCQ_COVER_FIELDS,
    RUNS_API_BASE_URL,
)
from detection import detect_document
from processing import (
    enhance_scan,
    detect_qr_code,
    _encode_b64,
    scan_half,
    _ocr_handwriting,
    _ocr_printed,
    _ocr_trocr,
    _preprocess_for_ocr,
    _split_emplid_digits,
)

router = APIRouter()


async def _decode_upload(file: UploadFile) -> np.ndarray:
    contents = await file.read()
    np_arr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image file.")
    return image


def _extract_cover_fields(canonical: np.ndarray, fields: dict[str, tuple[int, int, int, int]]) -> dict:
    """
    Run the cover-field OCR pipeline on an already-scanned A4 cover image.

    `fields` maps field name -> (x, y, w, h) region on the canonical image,
    e.g. COVER_FIELDS or MCQ_COVER_FIELDS, so this can be reused across page layouts.

    Returns a dict with 'fields', 'crops', 'confidences', 'scan_dimensions', and
    'regions_used', matching the /extract-cover response shape. 'confidences' maps
    each field to a 0-1 OCR confidence score (per-digit scores for "Emplid", under
    the key "Emplid_digits").
    """
    denoised = cv2.fastNlMeansDenoisingColored(canonical, h=10, hColor=10)

    extracted: dict[str, str] = {}
    crops_b64: dict[str, str] = {}
    confidences: dict[str, float] = {}
    for field, (x, y, w, h) in fields.items():
        crop = denoised[y : y + h, x : x + w]
        if crop.size == 0:
            extracted[field] = ""
            crops_b64[field] = ""
            confidences[field] = 0.0
            continue
        if field == "Emplid":
            digit_crops = _split_emplid_digits(crop)
            digit_chars = []
            digit_confidences = []
            processed_digits = []
            for dc in digit_crops:
                if dc.size == 0:
                    digit_chars.append("")
                    digit_confidences.append(0.0)
                    continue
                ocr_input = _preprocess_for_ocr(dc)
                processed_digits.append(ocr_input)
                try:
                    raw, conf = _ocr_trocr(ocr_input)
                    digits_only = re.sub(r"\D", "", raw)
                    digit_chars.append(digits_only[:1] if digits_only else "?")
                    digit_confidences.append(conf)
                except Exception:
                    digit_chars.append("?")
                    digit_confidences.append(0.0)
            extracted[field] = "".join(digit_chars)
            crops_b64[field] = _encode_b64(cv2.hconcat(processed_digits)) if processed_digits else ""
            confidences["Emplid_digits"] = digit_confidences
            confidences[field] = min(digit_confidences) if digit_confidences else 0.0
            continue
        if field == "Course Code":
            ocr_input = _preprocess_for_ocr(crop)
            crops_b64[field] = _encode_b64(ocr_input)
            try:
                raw, conf = _ocr_trocr(ocr_input)
                extracted[field] = re.sub(r"[^A-Za-z0-9]", "", raw)
                confidences[field] = conf
            except Exception as exc:
                extracted[field] = f"[OCR error: {exc}]"
                confidences[field] = 0.0
            continue

        ocr_input = _preprocess_for_ocr(crop)
        crops_b64[field] = _encode_b64(ocr_input)
        try:
            extracted[field], confidences[field] = _ocr_trocr(ocr_input)
        except Exception as exc:
            extracted[field] = f"[OCR error: {exc}]"
            confidences[field] = 0.0

    return {
        "fields": extracted,
        "crops": crops_b64,
        "confidences": confidences,
        "scan_dimensions": {"width": A4_WIDTH, "height": A4_HEIGHT},
        "regions_used": {k: list(v) for k, v in fields.items()},
    }


def _process_exam_folder(input_dir: Path, output_dir: Path, method: str, enhance: bool) -> dict:
    """
    Run the process-page pipeline over every image in `input_dir` (sorted by
    filename), writing scanned pages + student_info.txt + combined.pdf into
    `output_dir`.
    """
    image_files = sorted(
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTS
    )
    if not image_files:
        raise HTTPException(status_code=400, detail="No images found in folder.")

    output_dir.mkdir(parents=True, exist_ok=True)

    student_info: dict | None = None
    page_paths: list[Path] = []
    page_counter = 0
    total = len(image_files)

    for index, img_path in enumerate(image_files, start=1):
        print(f"[{index}/{total}] {img_path.name}: reading image...")
        image = cv2.imread(str(img_path))
        if image is None:
            print(f"[{index}/{total}] {img_path.name}: skipped (unreadable)")
            continue

        qr_found, _qr_data = detect_qr_code(image)

        if qr_found:
            print(f"[{index}/{total}] {img_path.name}: cover page detected, scanning...")
            corners = detect_document(image, method)
            warped = four_point_transform(image, corners.reshape(4, 2))
            warped = cv2.resize(warped, (A4_WIDTH, A4_HEIGHT), interpolation=cv2.INTER_CUBIC)
            scanned = enhance_scan(warped) if enhance else warped
            print(f"[{index}/{total}] {img_path.name}: running OCR on cover fields...")
            try:
                extraction = _extract_cover_fields(warped, COVER_FIELDS)
                student_info = extraction["fields"]
                print(f"[{index}/{total}] {img_path.name}: OCR done -> {student_info}")
            except Exception as exc:
                student_info = {"error": str(exc)}
                print(f"[{index}/{total}] {img_path.name}: OCR failed -> {exc}")

            page_counter += 1
            page_path = output_dir / f"page_{page_counter:03d}_cover.png"
            cv2.imwrite(str(page_path), scanned)
            page_paths.append(page_path)
            print(f"[{index}/{total}] {img_path.name}: saved {page_path.name}")
        else:
            print(f"[{index}/{total}] {img_path.name}: booklet spread, splitting...")
            corners = detect_document(image, method)
            warped = four_point_transform(image, corners.reshape(4, 2))
            spread = cv2.resize(warped, (A3_WIDTH, A3_HEIGHT), interpolation=cv2.INTER_CUBIC)
            mid = A3_WIDTH // 2
            halves = [spread[:, :mid], spread[:, mid:]]
            for half in halves:
                page = enhance_scan(half) if enhance else half
                page_counter += 1
                page_path = output_dir / f"page_{page_counter:03d}.png"
                cv2.imwrite(str(page_path), page)
                page_paths.append(page_path)
                print(f"[{index}/{total}] {img_path.name}: saved {page_path.name}")

    print(f"Writing student_info.txt and combined.pdf for {len(page_paths)} page(s)...")
    info_path = output_dir / "student_info.txt"
    with open(info_path, "w") as f:
        if student_info:
            for key, value in student_info.items():
                f.write(f"{key}: {value}\n")
        else:
            f.write("No cover page detected.\n")

    pdf_path = output_dir / "combined.pdf"
    pil_images = [PILImage.open(p).convert("RGB") for p in page_paths]
    if pil_images:
        PILImage.init()  # registers the JPEG codec save handler used internally by PDF export
        pil_images[0].save(pdf_path, save_all=True, append_images=pil_images[1:])
    print(f"Done: {len(page_paths)} page(s) processed -> {output_dir}")

    return {
        "output_dir": str(output_dir),
        "num_pages": len(page_paths),
        "student_info": student_info or {},
        "pdf_filename": pdf_path.name,
        "page_files": [p.name for p in page_paths],
    }


def _parse_class_list(raw: bytes) -> list[dict]:
    """
    Parse a class-list CSV export into a list of student dicts.

    Columns by position: Name, Pronouns, UserName, Email, Role, LastAccessed.
    Only 'Student' rows are kept, and only Name / UserName / Role are retained
    — UserName is the student/Emplid number used to match scanned booklets to
    the roster. A leading header row is detected and skipped; duplicate
    usernames collapse to their first occurrence.
    """
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    students: list[dict] = []
    seen: set[str] = set()
    for i, row in enumerate(reader):
        if len(row) < 5:
            continue
        name, _pronouns, username, _email, role = (cell.strip() for cell in row[:5])
        if i == 0 and name.lower() == "name":
            continue  # header row
        if role.lower() != "student":
            continue
        if not username or username.upper() in seen:
            continue
        seen.add(username.upper())
        students.append({"name": name, "username": username, "role": role})
    return students


def _student_status(row: dict) -> str:
    """Derived roster status: 'scanned' (expected + a booklet matched),
    'missing' (expected, no booklet yet), or 'unexpected' (a booklet matched
    someone not on the class list)."""
    if row["scanned"]:
        return "scanned" if row["expected"] else "unexpected"
    return "missing"


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/scan")
async def scan_document(
    file: UploadFile = File(...),
    method: str = Form(default="colour"),
    enhance: bool = Form(default=True),
):
    """
    Upload an image → detect document → perspective transform → return scan.

    Params:
        method:  'colour' (default) or 'corner' — detection strategy.
        enhance: Apply adaptive-threshold enhancement (default True).
    """
    image = await _decode_upload(file)

    corners = detect_document(image, method)
    warped = four_point_transform(image, corners.reshape(4, 2))
    warped = cv2.resize(warped, (A4_WIDTH, A4_HEIGHT), interpolation=cv2.INTER_CUBIC)

    result = enhance_scan(warped) if enhance else warped

    _, buffer = cv2.imencode(".png", result)
    return StreamingResponse(
        io.BytesIO(buffer.tobytes()),
        media_type="image/png",
        headers={"Content-Disposition": "attachment; filename=scanned.png"},
    )


@router.post("/detect-preview")
async def detect_preview(
    file: UploadFile = File(...),
    method: str = Form(default="colour"),
):
    """Returns the original image with detected corners highlighted."""
    image = await _decode_upload(file)

    corners = detect_document(image, method)
    preview = image.copy()

    pts = corners.reshape(4, 2).astype(int)
    cv2.polylines(preview, [pts], isClosed=True, color=(0, 255, 100), thickness=3)
    for pt in pts:
        cv2.circle(preview, tuple(pt), 10, (0, 120, 255), -1)
        cv2.circle(preview, tuple(pt), 10, (255, 255, 255), 2)

    _, buffer = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return StreamingResponse(
        io.BytesIO(buffer.tobytes()),
        media_type="image/jpeg",
    )

@router.post("/split-booklet")
async def split_booklet(
    file: UploadFile = File(...),
    method: str = Form(default="colour"),
    enhance: bool = Form(default=True),
):
    """
    Upload a photo of an open A4 booklet (two pages side-by-side).
    Returns a ZIP archive with 'page_left.png' and 'page_right.png',
    each at A4 dimensions (2480 × 3508 px at 300 DPI).
    """
    image = await _decode_upload(file)

    corners = detect_document(image, method)
    warped = four_point_transform(image, corners.reshape(4, 2))
    spread = cv2.resize(warped, (A3_WIDTH, A3_HEIGHT), interpolation=cv2.INTER_CUBIC)

    mid = A3_WIDTH // 2
    halves = [spread[:, :mid], spread[:, mid:]]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, half in zip(["page_left.png", "page_right.png"], halves):
            page = enhance_scan(half) if enhance else half
            _, buf = cv2.imencode(".png", page)
            zf.writestr(name, buf.tobytes())

    zip_buf.seek(0)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=booklet_pages.zip"},
    )


@router.post("/process-page")
async def process_page(
    file: UploadFile = File(...),
    method: str = Form(default="colour"),
    enhance: bool = Form(default=True),
):
    """
    Smart routing endpoint for exam booklet images.

    - If a QR code is detected: scans the full image, runs OCR, and returns
      JSON with the scanned image (base64 PNG) and extracted text.
    - If no QR code is detected: treats image as an open booklet spread, scans
      each half independently, and returns JSON with both pages as base64 PNGs.
    """
    image = await _decode_upload(file)

    h, w = image.shape[:2]
    qr_found, qr_data = detect_qr_code(image)

    if qr_found:
        corners = detect_document(image, method)
        warped = four_point_transform(image, corners.reshape(4, 2))
        warped = cv2.resize(warped, (A4_WIDTH, A4_HEIGHT), interpolation=cv2.INTER_CUBIC)
        scanned = enhance_scan(warped) if enhance else warped
        try:
            extraction = _extract_cover_fields(warped, COVER_FIELDS)
            ocr_text = "success"
        except Exception as exc:
            ocr_text = f"[OCR unavailable: {exc}]"

        return JSONResponse({
            "type": "first_page",
            "qr_data": qr_data,
            "scanned_image": _encode_b64(scanned),
            "ocr_text": ocr_text,
            **extraction,
        })
    else:
        corners = detect_document(image, method)
        warped = four_point_transform(image, corners.reshape(4, 2))
        spread = cv2.resize(warped, (A3_WIDTH, A3_HEIGHT), interpolation=cv2.INTER_CUBIC)
        mid = A3_WIDTH // 2
        halves = [spread[:, :mid], spread[:, mid:]]
        pages = []
        for i, half in enumerate(halves, start=1):
            page = enhance_scan(half) if enhance else half
            pages.append({"page": i, "scanned_image": _encode_b64(page)})
        return JSONResponse({"type": "booklet", "pages": pages})


@router.post("/extract-cover")
async def extract_cover(
    file: UploadFile = File(...),
    method: str = Form(default="colour"),
):
    """
    Upload a workbook cover photo → scan it → OCR field regions → return JSON.

    Returns:
        {
          "fields": { "Emplid": "...", "Course Code": "...", "subject": "..." },
          "scan_dimensions": { "width": 2480, "height": 3508 },
          "regions_used": { "Emplid": [x, y, w, h], ... }
        }
    """
    image = await _decode_upload(file)

    corners = detect_document(image, method)
    warped = four_point_transform(image, corners.reshape(4, 2))
    canonical = cv2.resize(warped, (A4_WIDTH, A4_HEIGHT), interpolation=cv2.INTER_CUBIC)

    result = _extract_cover_fields(canonical, COVER_FIELDS)
    return JSONResponse(result)


@router.post("/extract-mcq-cover")
async def extract_mcq_cover(
    file: UploadFile = File(...),
    method: str = Form(default="colour"),
):
    """
    Upload an MCQ answer-sheet photo → scan it → OCR MCQ field regions → return JSON.

    Same response shape as /extract-cover, using MCQ_COVER_FIELDS (placeholder
    regions — calibrate against a real MCQ scan before relying on this).
    """
    image = await _decode_upload(file)

    corners = detect_document(image, method)
    warped = four_point_transform(image, corners.reshape(4, 2))
    canonical = cv2.resize(warped, (A4_WIDTH, A4_HEIGHT), interpolation=cv2.INTER_CUBIC)

    result = _extract_cover_fields(canonical, MCQ_COVER_FIELDS)
    return JSONResponse(result)


@router.post("/process-folder")
async def process_folder(
    folder_path: str | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
    method: str = Form(default="colour"),
    enhance: bool = Form(default=True),
):
    """
    Batch-process a folder of exam-script page photos.

    - `folder_path`: absolute path to a folder on the server's filesystem.
      Output is written to a new `output_<timestamp>/` folder inside it, and
      the response is JSON describing the result.
    - `files`: uploaded image files (used when the client can't supply a
      server-side path, e.g. a browser folder drop). Output is staged in a
      temp directory and returned as a downloadable ZIP.

    Exactly one of `folder_path` or `files` must be provided.
    """
    if folder_path:
        input_dir = Path(folder_path)
        if not input_dir.is_dir():
            raise HTTPException(status_code=400, detail="folder_path is not a valid directory.")

        output_dir = input_dir / f"output_{datetime.now():%Y%m%d_%H%M%S}"
        result = _process_exam_folder(input_dir, output_dir, method, enhance)
        return JSONResponse({"mode": "path", **result})

    elif files:
        staging = Path(tempfile.mkdtemp(prefix="examscan_"))
        try:
            input_dir = staging / "input"
            output_dir = staging / "output"
            input_dir.mkdir()

            for upload in files:
                contents = await upload.read()
                (input_dir / Path(upload.filename).name).write_bytes(contents)

            _process_exam_folder(input_dir, output_dir, method, enhance)

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in output_dir.iterdir():
                    zf.write(p, arcname=p.name)
            zip_buf.seek(0)

            return StreamingResponse(
                zip_buf,
                media_type="application/zip",
                headers={"Content-Disposition": "attachment; filename=exam_output.zip"},
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    else:
        raise HTTPException(status_code=400, detail="Provide either folder_path or files.")


@router.post("/demo_exam_folder")
async def demo_exam_folder(
    run_id: str = Form(...),
    method: str = Form(default="colour"),
    enhance: bool = Form(default=True),
):
    """
    Batch-process a run's exam-script pages fetched from the remote runs API
    (GET {RUNS_API_BASE_URL}/api/runs/{run_id}/archive) instead of a local
    folder or upload.

    Functionally identical to /process-folder's pipeline, but the input
    images are downloaded as a ZIP archive. Output is persisted to
    software/demo_output/<run_id>/; nothing is returned to the caller on
    success.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{RUNS_API_BASE_URL}/api/runs/{run_id}/archive")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to download archive for run {run_id} (status {resp.status_code}).",
        )

    staging = Path(tempfile.mkdtemp(prefix="examscan_demo_"))
    try:
        input_dir = staging / "input"
        input_dir.mkdir()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(input_dir)

        output_dir = Path(__file__).parent / "demo_output" / run_id
        _process_exam_folder(input_dir, output_dir, method, enhance)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return Response(status_code=204)


DEMO_RUNS_FILE = Path(__file__).parent / "demo_runs.json"


@router.post("/runs")
async def fetch_runs():
    """
    Fetch the current list of run ids from the remote runs API
    (GET {RUNS_API_BASE_URL}/api/runs), persist it to demo_runs.json, and
    return it to the caller.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{RUNS_API_BASE_URL}/api/runs")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach runs API: {e}")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch runs (status {resp.status_code}).",
        )

    data = resp.json()
    DEMO_RUNS_FILE.write_text(resp.text)
    return JSONResponse(data)


@router.get("/runs")
async def get_stored_runs():
    """Return the run ids most recently persisted by POST /runs, or an empty list."""
    if not DEMO_RUNS_FILE.exists():
        return JSONResponse([])
    return JSONResponse(json.loads(DEMO_RUNS_FILE.read_text()))


@router.get("/runs/{run_id}/archive")
async def download_run_archive(run_id: str):
    """
    Proxy the raw ZIP archive for a run (GET {RUNS_API_BASE_URL}/api/runs/{id}/archive)
    straight through to the caller, with no processing.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{RUNS_API_BASE_URL}/api/runs/{run_id}/archive")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach runs API: {e}")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to download archive for run {run_id} (status {resp.status_code}).",
        )

    return StreamingResponse(
        io.BytesIO(resp.content),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=run_{run_id}.zip"},
    )


@router.get("/samples")
async def list_samples():
    """Return sorted list of sample image filenames."""
    if not SAMPLE_DIR.exists():
        return JSONResponse({"files": []})
    files = sorted(
        f.name for f in SAMPLE_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTS
    )
    return JSONResponse({"files": files})


@router.get("/samples/{filename}")
async def get_sample(filename: str):
    """Serve a single sample image by filename."""
    safe = Path(filename).name
    file_path = SAMPLE_DIR / safe
    if not file_path.exists() or file_path.suffix.lower() not in _IMAGE_EXTS:
        raise HTTPException(status_code=404, detail="Sample not found")
    return FileResponse(file_path)


@router.post("/sessions")
async def create_session(
    session_code: str = Form(...),
    operator_name: str = Form(...),
    test_date: str = Form(...),
    course_code: str = Form(...),
    class_list: UploadFile | None = File(default=None),
):
    """
    Start a scan session (course code, test date, operator) that persists
    for the lifetime of a scanning run. Booklets are then submitted against
    this session via POST /sessions/{session_code}/booklets.

    An optional `class_list` CSV (Name, Pronouns, UserName, Email, Role,
    LastAccessed) seeds the session's expected-student roster: 'Student' rows
    only, storing Name / UserName / Role. It can also be uploaded later via
    POST /sessions/{session_code}/class-list.
    """
    try:
        session_id = await run_in_threadpool(
            db.create_session, session_code, operator_name, test_date, course_code
        )
    except db.DuplicateSessionError:
        raise HTTPException(status_code=409, detail=f"session_code '{session_code}' already exists.")
    except ValueError:
        raise HTTPException(status_code=400, detail="test_date must be in YYYY-MM-DD format.")

    students_imported = 0
    if class_list is not None:
        students = _parse_class_list(await class_list.read())
        roster = await run_in_threadpool(db.import_session_students, session_id, students)
        students_imported = roster["imported"]

    return JSONResponse({
        "session_id": session_id,
        "session_code": session_code,
        "students_imported": students_imported,
    })


@router.post("/sessions/{session_code}/class-list")
async def import_class_list(session_code: str, class_list: UploadFile = File(...)):
    """
    Upload (or re-upload) the class-list CSV for an existing session.

    Rows are upserted by username: a re-upload refreshes names/roles and
    re-marks everyone as expected without losing scan progress. Booklets
    already scanned in this session are re-checked against the new roster.
    """
    session = await run_in_threadpool(db.get_session, session_code)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown session_code '{session_code}'.")

    students = _parse_class_list(await class_list.read())
    roster = await run_in_threadpool(db.import_session_students, session["id"], students)
    return JSONResponse({
        "session_code": session_code,
        "students_imported": roster["imported"],
        "booklets_newly_matched": roster["matched"],
    })


@router.get("/sessions/{session_code}/students")
async def list_session_students(session_code: str):
    """
    The expected-student roster for a session, each row tagged with a derived
    `status`: 'missing', 'scanned', or 'unexpected'.
    """
    session = await run_in_threadpool(db.get_session, session_code)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown session_code '{session_code}'.")

    rows = await run_in_threadpool(db.get_session_students, session["id"])
    students = [{**r, "status": _student_status(r)} for r in rows]
    return JSONResponse({"session_code": session_code, "students": students})


@router.get("/sessions/{session_code}/reconciliation")
async def session_reconciliation(session_code: str):
    """
    Expected-vs-scanned summary for a session: who on the class list still
    hasn't been scanned, and which scanned booklets matched nobody.
    """
    session = await run_in_threadpool(db.get_session, session_code)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown session_code '{session_code}'.")

    rows = await run_in_threadpool(db.get_session_students, session["id"])
    unmatched = await run_in_threadpool(db.get_unmatched_booklets, session["id"])
    missing = [
        {"name": r["name"], "username": r["username"]}
        for r in rows
        if r["expected"] and not r["scanned"]
    ]
    return JSONResponse({
        "session_code": session_code,
        "expected_count": sum(1 for r in rows if r["expected"]),
        "scanned_count": sum(1 for r in rows if r["expected"] and r["scanned"]),
        "missing": missing,
        "unmatched_booklets": unmatched,
    })


@router.post("/sessions/{session_code}/booklets")
async def add_booklet(
    session_code: str,
    folder_path: str = Form(...),
    method: str = Form(default="colour"),
    enhance: bool = Form(default=True),
):
    """
    Process one booklet's images (via _process_exam_folder) against an
    existing scan session, compare the OCR'd course code against the
    session's declared course code, and persist the PDF + metadata to MySQL.

    Course-code mismatches are stored and flagged (course_code_verified =
    False), never rejected. A repeat Emplid within the same session is
    rejected (409) rather than overwritten.
    """
    session = await run_in_threadpool(db.get_session, session_code)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown session_code '{session_code}'.")

    input_dir = Path(folder_path)
    if not input_dir.is_dir():
        raise HTTPException(status_code=400, detail="folder_path is not a valid directory.")

    staging_output = Path(tempfile.mkdtemp(prefix="examscan_booklet_"))
    try:
        result = _process_exam_folder(input_dir, staging_output, method, enhance)

        student_info = result["student_info"]
        emplid = student_info.get("Emplid", "")
        scanned_course = student_info.get("Course Code", "")
        verified = scanned_course.strip().upper() == session["course_code"].strip().upper()

        final_dir = STORAGE_ROOT / session_code / (emplid or "unknown")

        booklet = await run_in_threadpool(
            db.insert_booklet,
            session["id"],
            emplid,
            scanned_course,
            verified,
            result["num_pages"],
            str(final_dir / "combined.pdf"),
        )
        booklet_id = booklet["booklet_id"]

        if final_dir.exists():
            shutil.rmtree(final_dir)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging_output), str(final_dir))
    except db.DuplicateEmplidError:
        raise HTTPException(
            status_code=409,
            detail=f"Emplid '{emplid}' already recorded for session '{session_code}'.",
        )
    finally:
        shutil.rmtree(staging_output, ignore_errors=True)  # no-op once already moved

    return JSONResponse({
        "booklet_id": booklet_id,
        "verified": verified,
        "matched_student_id": booklet["student_id"],
        "on_class_list": booklet["student_id"] is not None,
        "student_info": student_info,
    })