from __future__ import annotations

import cv2
import numpy as np


def validate_quadrilateral(approx, image_shape) -> bool:
    """
    Reject contours that are too small, hug the image border,
    or cover nearly the entire image.
    """
    h, w = image_shape[:2]
    area = cv2.contourArea(approx)

    if area < 0.05 * w * h:
        return False
    if area > 0.90 * w * h:
        return False

    pts = approx.reshape(-1, 2)
    margin = max(int(max(w, h) * 0.01), 5)
    on_edge = sum(
        1 for (px, py) in pts
        if px <= margin or px >= w - margin or
           py <= margin or py >= h - margin
    )
    if on_edge >= 1:
        return False

    return True


def find_best_quad(contours, image_shape) -> tuple:
    """
    Walk through contours (largest-first) and return the best valid
    4-point polygon.  Tries several approximation epsilons per contour.
    Returns (contour, area) or (None, 0).
    """
    eps_factors = [0.02, 0.015, 0.025, 0.03, 0.04, 0.05]
    best = None
    best_area = 0

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 1000 or area <= best_area:
            continue
        peri = cv2.arcLength(contour, True)

        for eps in eps_factors:
            approx = cv2.approxPolyDP(contour, eps * peri, True)
            if len(approx) == 4 and validate_quadrilateral(approx, image_shape):
                best = approx
                best_area = area
                break

        if best is None or area > best_area:
            rect = cv2.minAreaRect(contour)
            box = np.int32(cv2.boxPoints(rect))
            if validate_quadrilateral(box, image_shape):
                best = box
                best_area = area

    return best, best_area


def erase_border(mask, fraction: float = 0.001) -> None:
    """Zero-out a thin strip around the image edge of a mask."""
    h, w = mask.shape[:2]
    b = max(int(max(w, h) * fraction), 5)
    mask[:b, :] = 0
    mask[-b:, :] = 0
    mask[:, :b] = 0
    mask[:, -b:] = 0


def detect_by_corner(image: np.ndarray) -> np.ndarray:
    """
    Find the paper by detecting edges with Canny and locating the largest
    quadrilateral contour that isn't the image border.
    """
    h, w = image.shape[:2]
    fallback = np.array([[0, 0], [w, 0], [w, h], [0, h]])

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 30, 100)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.dilate(edges, kernel, iterations=2)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=3)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    quad, _ = find_best_quad(contours, image.shape)
    return quad if quad is not None else fallback


def detect_by_colour(image: np.ndarray) -> np.ndarray:
    """
    Detect a white / light paper against a distinctly coloured background.

    Multi-pass strategy — picks the best result across three masks:
      A. LAB lightness  (Otsu)           — bright paper vs darker surface
      B. HSV saturation (Otsu, inverted) — unsaturated paper vs colourful background
      C. Intersection A ∩ B              — highest confidence

    Each mask is cleaned and searched; the largest valid quad wins.
    Falls back to detect_by_corner if no quad is found.
    """
    h, w = image.shape[:2]

    max_dim = 2000
    scale = min(max_dim / w, max_dim / h, 1.0)
    if scale < 1.0:
        small = cv2.resize(image, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    else:
        small = image.copy()

    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    _, mask_l = cv2.threshold(lab[:, :, 0], 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    _, mask_s = cv2.threshold(hsv[:, :, 1], 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    mask_both = cv2.bitwise_and(mask_l, mask_s)

    for m in [mask_l, mask_s, mask_both]:
        erase_border(m)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    best_quad = None
    best_area = 0

    for mask in [mask_both, mask_l, mask_s]:
        cleaned = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=4)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN,  kernel, iterations=2)

        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        quad, area = find_best_quad(contours, small.shape)
        if quad is not None and area > best_area:
            best_quad = quad
            best_area = area

    if best_quad is not None and scale < 1.0:
        best_quad = (best_quad.astype("float64") / scale).astype("int32")

    return best_quad if best_quad is not None else detect_by_corner(image)


def detect_document(image: np.ndarray, method: str = "colour") -> np.ndarray:
    """
    Detect the A4 page boundary.
    method='colour' (default) or 'corner'.
    Always returns a 4-point array (falls back to full image frame if needed).
    """
    if method == "corner":
        return detect_by_corner(image)
    return detect_by_colour(image)
