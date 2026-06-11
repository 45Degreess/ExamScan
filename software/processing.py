from __future__ import annotations

import base64

import cv2
import numpy as np
from imutils.perspective import four_point_transform

from constants import A4_WIDTH, A4_HEIGHT
from detection import detect_document


def enhance_scan(warped: np.ndarray) -> np.ndarray:
    """Adaptive threshold for a clean black-and-white scan look."""
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 10
    )


# ── OCR helpers (lazy-loaded to avoid slowing down startup) ──────────────────

_easyocr_reader = None


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr  # noqa: PLC0415
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _easyocr_reader


def _ocr_handwriting(crop: np.ndarray) -> str:
    """EasyOCR on a grayscale numpy crop. Best for handwritten text."""
    reader = _get_easyocr_reader()
    results = reader.readtext(crop, detail=0, paragraph=True)
    return " ".join(results).strip()


def _ocr_printed(crop: np.ndarray) -> str:
    """pytesseract on a grayscale numpy crop. Falls back to EasyOCR if Tesseract is not installed."""
    try:
        import pytesseract
        from PIL import Image as PILImage
        pil_img = PILImage.fromarray(crop)
        return pytesseract.image_to_string(pil_img, config="--psm 6 --oem 3").strip()
    except (ImportError, Exception):
        return _ocr_handwriting(crop)


# ── QR / booklet helpers ─────────────────────────────────────────────────────

def detect_qr_code(image: np.ndarray) -> tuple[bool, str]:
    """Attempt to decode a QR code anywhere in the image. Returns (found, data)."""
    detector = cv2.QRCodeDetector()
    data, bbox, _ = detector.detectAndDecode(image)
    if data:
        return True, data
    return False, ""


def _encode_b64(img: np.ndarray) -> str:
    """PNG-encode a numpy image and return a base64 string."""
    _, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf.tobytes()).decode()


def scan_half(crop: np.ndarray, method: str, enhance: bool) -> np.ndarray:
    """Detect, warp, resize to A4, and optionally enhance a cropped half-image."""
    corners = detect_document(crop, method)
    warped = four_point_transform(crop, corners.reshape(4, 2))
    warped = cv2.resize(warped, (A4_WIDTH, A4_HEIGHT), interpolation=cv2.INTER_CUBIC)
    return enhance_scan(warped) if enhance else cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
