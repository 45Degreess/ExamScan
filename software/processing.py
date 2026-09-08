from __future__ import annotations

import base64
import os

import cv2
import numpy as np
from imutils.perspective import four_point_transform

from constants import A4_WIDTH, A4_HEIGHT, EMPLID_PADDING
from detection import detect_document

_MODEL_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".model_cache")


def enhance_scan(warped: np.ndarray) -> np.ndarray:
    """CLAHE contrast enhancement on the L channel — keeps full colour."""
    lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


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


_trocr_processor = None
_trocr_model = None
_trocr_device = None


def _get_trocr_device():
    global _trocr_device
    if _trocr_device is None:
        import torch  # noqa: PLC0415
        if torch.backends.mps.is_available():
            _trocr_device = "mps"
        elif torch.cuda.is_available():
            _trocr_device = "cuda"
        else:
            _trocr_device = "cpu"
    return _trocr_device


def _get_trocr():
    global _trocr_processor, _trocr_model
    if _trocr_processor is None:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        _trocr_processor = TrOCRProcessor.from_pretrained(
            "microsoft/trocr-base-handwritten", cache_dir=_MODEL_CACHE_DIR
        )
        _trocr_model = VisionEncoderDecoderModel.from_pretrained(
            "microsoft/trocr-base-handwritten", cache_dir=_MODEL_CACHE_DIR
        )
        _trocr_model = _trocr_model.to(_get_trocr_device())
    return _trocr_processor, _trocr_model


def _split_emplid_digits(crop: np.ndarray, num_digits: int = 7, padding: int = EMPLID_PADDING) -> list[np.ndarray]:
    """Evenly split a full Emplid field crop into `num_digits` single-digit
    sub-crops, trimming `padding` px total at each internal separator line."""
    h, w = crop.shape[:2]
    cell_w = w // num_digits
    digits = []
    for i in range(num_digits):
        left = i * cell_w + (padding // 2 if i > 0 else 0)
        right = (i + 1) * cell_w - (padding // 2 if i < num_digits - 1 else 0)
        left, right = max(0, left), min(w, right)
        digits.append(crop[:, left:right] if right > left else crop[:, 0:0])
    return digits


def _preprocess_for_ocr(crop: np.ndarray) -> np.ndarray:
    """Grayscale + adaptive threshold to boost OCR contrast on a field crop."""
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )


def _ocr_trocr(crop: np.ndarray) -> tuple[str, float]:
    """TrOCR on a numpy crop (grayscale or BGR). Best for handwritten text.

    Returns (text, confidence), where confidence is the geometric mean of the
    per-token softmax probabilities of the generated sequence (0-1).
    """
    import torch
    from PIL import Image as PILImage
    processor, model = _get_trocr()
    if crop.ndim == 2:
        pil = PILImage.fromarray(crop).convert("RGB")
    else:
        pil = PILImage.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    pixel_values = processor(pil, return_tensors="pt").pixel_values.to(_get_trocr_device())
    outputs = model.generate(
        pixel_values,
        max_length=50,
        num_beams=1,
        output_scores=True,
        return_dict_in_generate=True,
    )
    text = processor.batch_decode(outputs.sequences, skip_special_tokens=True)[0].strip()

    token_probs = []
    for step_scores, token_id in zip(outputs.scores, outputs.sequences[0, 1:]):
        if token_id == processor.tokenizer.pad_token_id:
            continue
        step_probs = torch.softmax(step_scores[0], dim=-1)
        token_probs.append(step_probs[token_id].item())
    confidence = float(np.prod(token_probs) ** (1.0 / len(token_probs))) if token_probs else 0.0

    return text, confidence


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
    return enhance_scan(warped) if enhance else warped
