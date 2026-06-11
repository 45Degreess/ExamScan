from __future__ import annotations

import io
import zipfile
from pathlib import Path

import cv2
import numpy as np
from imutils.perspective import four_point_transform
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

SAMPLE_DIR = Path(__file__).parent / "sample_images"
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

from constants import A4_WIDTH, A4_HEIGHT, A3_WIDTH, A3_HEIGHT, COVER_FIELDS
from detection import detect_document
from processing import (
    enhance_scan,
    detect_qr_code,
    _encode_b64,
    scan_half,
    _ocr_handwriting,
    _ocr_printed,
    _ocr_trocr,
)

router = APIRouter()


async def _decode_upload(file: UploadFile) -> np.ndarray:
    contents = await file.read()
    np_arr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image file.")
    return image


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

    result = enhance_scan(warped) if enhance else cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)

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
            page = enhance_scan(half) if enhance else cv2.cvtColor(half, cv2.COLOR_BGR2GRAY)
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
        scanned = enhance_scan(warped) if enhance else cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        try:
            ocr_text = _ocr_handwriting(scanned)
        except Exception as exc:
            ocr_text = f"[OCR unavailable: {exc}]"
        return JSONResponse({
            "type": "first_page",
            "qr_data": qr_data,
            "scanned_image": _encode_b64(scanned),
            "ocr_text": ocr_text,
        })
    else:
        corners = detect_document(image, method)
        warped = four_point_transform(image, corners.reshape(4, 2))
        spread = cv2.resize(warped, (A3_WIDTH, A3_HEIGHT), interpolation=cv2.INTER_CUBIC)
        mid = A3_WIDTH // 2
        halves = [spread[:, :mid], spread[:, mid:]]
        pages = []
        for i, half in enumerate(halves, start=1):
            page = enhance_scan(half) if enhance else cv2.cvtColor(half, cv2.COLOR_BGR2GRAY)
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

    gray = cv2.cvtColor(canonical, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    extracted: dict[str, str] = {}
    crops_b64: dict[str, str] = {}
    for field, (x, y, w, h) in COVER_FIELDS.items():
        crop = denoised[y : y + h, x : x + w]
        if crop.size == 0:
            extracted[field] = ""
            crops_b64[field] = ""
            continue
        crops_b64[field] = _encode_b64(crop)
        try:
            extracted[field] = _ocr_trocr(crop)
        except Exception as exc:
            extracted[field] = f"[OCR error: {exc}]"

    return JSONResponse({
        "fields": extracted,
        "crops": crops_b64,
        "scan_dimensions": {"width": A4_WIDTH, "height": A4_HEIGHT},
        "regions_used": {k: list(v) for k, v in COVER_FIELDS.items()},
    })


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