from __future__ import annotations

import base64
import os
import re

import cv2
import numpy as np
from imutils.perspective import four_point_transform

from constants import A4_WIDTH, A4_HEIGHT, EMPLID_PADDING
from detection import detect_document

_MODEL_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".model_cache")


def load_rig_overlay(path) -> np.ndarray:
    """Load a rig overlay from disk. Raises ValueError if the file has no alpha channel."""
    overlay = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if overlay is None or overlay.ndim != 3 or overlay.shape[2] != 4:
        raise ValueError(f"Rig overlay at {path} must be a 4-channel BGRA PNG")
    return overlay


def apply_rig_overlay(image: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    """
    apply overlay on top of image, hiding rig hardware under the overlay's opaque border while its hole lets the original image show through untouched.

    Resizes overlay to image.shape[:2] first if dimensions differ.
    """
    if overlay.shape[:2] != image.shape[:2]:
        h, w = image.shape[:2]
        overlay_bgr = cv2.resize(overlay[:, :, :3], (w, h), interpolation=cv2.INTER_LINEAR)
        overlay_a = cv2.resize(overlay[:, :, 3], (w, h), interpolation=cv2.INTER_NEAREST)
    else:
        overlay_bgr, overlay_a = overlay[:, :, :3], overlay[:, :, 3]

    alpha = (overlay_a.astype(np.float32) / 255.0)[:, :, None]
    blended = overlay_bgr.astype(np.float32) * alpha + image.astype(np.float32) * (1 - alpha)
    return blended.astype(np.uint8)


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
            _trocr_device = "mps" # mac
        elif torch.cuda.is_available():
            _trocr_device = "cuda" # nvidia
        else:
            _trocr_device = "cpu" # cpu
    return _trocr_device

# model loading
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
    """Evenly split a full Emplid field crop into `num_digits` single-digit crops,
    trimming `padding` px total at each internal separator line."""
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
        num_beams=1, # attempts at reading
        output_scores=True,
        return_dict_in_generate=True,
    )
    text = processor.batch_decode(outputs.sequences, skip_special_tokens=True)[0].strip() #remove non number readings

    # probabilities
    token_probs = []
    for step_scores, token_id in zip(outputs.scores, outputs.sequences[0, 1:]):
        if token_id == processor.tokenizer.pad_token_id:
            continue
        step_probs = torch.softmax(step_scores[0], dim=-1)
        token_probs.append(step_probs[token_id].item())
    confidence = float(np.prod(token_probs) ** (1.0 / len(token_probs))) if token_probs else 0.0

    return text, confidence


# ── Handwritten mark extraction (red pen) ─────────────────────────────────────

def _isolate_red_ink(bgr_crop: np.ndarray) -> np.ndarray:
    """HSV-threshold red pen strokes in a region crop. Returns a binary mask
    (255 = red ink) the same height/width as `bgr_crop`."""
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    mask = (
        cv2.inRange(hsv, (0, 70, 50), (10, 255, 255)) | cv2.inRange(hsv, (170, 70, 50), (180, 255, 255)) # range of red ink, picked at two extremes
    )
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


_MIN_DIGIT_AREA = 40  #


def _find_digit_components(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """labelling on the raw (undilated) red mask — each surviving component is one candidate digit stroke. No merging happens here; that's `_cluster_digits`'s job."""
    num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = []
    for i in range(1, num_labels):  # label 0 is the background
        x, y, w, h, area = stats[i]
        if area < _MIN_DIGIT_AREA:
            continue
        boxes.append((int(x), int(y), int(w), int(h)))
    return boxes


def _cluster_digits(
    components: list[tuple[int, int, int, int]],
) -> list[list[tuple[int, int, int, int]]]:
    """Group digit-stroke components into numbers by proximity, capped at 2 digits (called a blob). The merge threshold scales with the components' own size on this page rather than a fixed pixel constant.

    when more than two numbers are clustered together, the algorithm corrects itself by only keeping the first two digits as outlined and starting a new 'blob' from the next number

    """
    if not components: # if no numbers
        return []

    ordered = sorted(components, key=lambda c: c[0]) # sorts left to right
    widths = [w for (_x, _y, w, _h) in ordered]
    median_w = sorted(widths)[len(widths) // 2]
    gap_threshold = max(1, int(0.5 * median_w))

    clusters: list[list[tuple[int, int, int, int]]] = [[ordered[0]]]
    for box in ordered[1:]:
        prev_x, prev_y, prev_w, prev_h = clusters[-1][-1]
        x, y, _w, h = box
        gap = x - (prev_x + prev_w)
        vertically_aligned = y < prev_y + prev_h and prev_y < y + h
        if gap <= gap_threshold and vertically_aligned and len(clusters[-1]) < 2:
            clusters[-1].append(box)
        else:
            clusters.append([box])
    return clusters


def _mask_to_ocr_image(mask: np.ndarray) -> np.ndarray:
    """Red ink to black, everything else to white"""
    out = np.full(mask.shape, 255, dtype=np.uint8)
    out[mask > 0] = 0
    return out


def _extract_candidates_from_region(
    page_bgr: np.ndarray, region: tuple[int, int, int, int]
) -> list[dict]:
    """Isolate red ink inside `region`
    cluster it into candidate numbers (1-2 digits each)
    OCR each digit individually
    return
    [{"value": int, "confidence": float, "box": (x,y,w,h), "mask_crop": ndarray}, ...]
    for every cluster that reduces to at least one digit."""
    rx, ry, rw, rh = region
    crop = page_bgr[ry:ry + rh, rx:rx + rw]
    mask = _isolate_red_ink(crop)
    clusters = _cluster_digits(_find_digit_components(mask))

    candidates = []
    pad = 6 # margin for OCR reading around box
    for cluster in clusters:
        ordered = sorted(cluster, key=lambda c: c[0])  # left-to-right
        digits, confidences = [], []
        for (x, y, w, h) in ordered:
            y0, y1 = max(0, y - pad), min(crop.shape[0], y + h + pad)
            x0, x1 = max(0, x - pad), min(crop.shape[1], x + w + pad)
            text, confidence = _ocr_trocr(_mask_to_ocr_image(mask[y0:y1, x0:x1]))
            digit_text = re.sub(r"\D", "", text) # remove non-numbers
            if not digit_text:
                continue
            digits.append(digit_text[0])
            confidences.append(confidence)
        if not digits:
            continue

        xs = [c[0] for c in cluster]
        ys = [c[1] for c in cluster]
        x2s = [c[0] + c[2] for c in cluster]
        y2s = [c[1] + c[3] for c in cluster]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(x2s), max(y2s)

        candidates.append({
            "value": int("".join(digits)),
            "confidence": sum(confidences) / len(confidences),
            "box": (rx + bx0, ry + by0, bx1 - bx0, by1 - by0),
            "mask_crop": mask[by0:by1, bx0:bx1],
        })
    return candidates

""" unused as we need the mark crops for reference in debug method below"""
def extract_handwritten_mark(
    page_bgr: np.ndarray, regions: list[tuple[int, int, int, int]]
) -> dict:
    """Isolate red-pen ink inside each of `regions` on a canonical cover-page
    image, segment it into individual handwritten numbers, OCR each with
    TrOCR, and return the two highest numeric candidates pooled across every
    region.

    Returns {"mark": int | None, "mark_confidence": float | None,
             "mark_candidates": [int, ...]} — "mark" is the single highest
    number found (or None if nothing was read), "mark_candidates" holds up
    to the top two values for operator review.
    """
    pooled: list[dict] = []
    for region in regions:
        pooled.extend(_extract_candidates_from_region(page_bgr, region))

    pooled.sort(key=lambda c: c["value"], reverse=True)
    top2 = pooled[:2]
    return {
        "mark": top2[0]["value"] if top2 else None,
        "mark_confidence": top2[0]["confidence"] if top2 else None,
        "mark_candidates": [c["value"] for c in top2],
    }


def extract_handwritten_mark_debug(
    page_bgr: np.ndarray, regions: list[tuple[int, int, int, int]]
) -> dict:
    """Same extraction as extract_handwritten_mark, but returns every
    candidate (not just the top one) with its bounding box, a base64 crop of
    what TrOCR actually read, its region index, and which one was selected
    as the mark — for the /extract-mark debug endpoint."""
    pooled: list[dict] = []
    for idx, region in enumerate(regions):
        for c in _extract_candidates_from_region(page_bgr, region):
            pooled.append({**c, "region_index": idx})

    pooled.sort(key=lambda c: c["value"], reverse=True)

    candidates = [
        {
            "value": c["value"],
            "confidence": c["confidence"],
            "box": list(c["box"]),
            "region_index": c["region_index"],
            "crop": _encode_b64(c["mask_crop"]),
            "selected": i == 0,
        }
        for i, c in enumerate(pooled)
    ]
    return {
        "mark": pooled[0]["value"] if pooled else None,
        "mark_confidence": pooled[0]["confidence"] if pooled else None,
        "candidates": candidates,
        "regions_used": [list(r) for r in regions],
        "scan_dimensions": {"width": A4_WIDTH, "height": A4_HEIGHT},
    }


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
