from __future__ import annotations

A4_WIDTH  = 2480   # 210 mm at 300 DPI
A4_HEIGHT = 3508   # 297 mm at 300 DPI

A3_WIDTH  = A4_WIDTH * 2   # 4960 px
A3_HEIGHT = A4_HEIGHT      # 3508 px

# Crop coordinates defined on the A4_WIDTH × A4_HEIGHT canonical image.
# HOW TO CALIBRATE FOR YOUR WORKBOOK:
#   1. POST a sample cover photo to /scan and save the PNG (already 2480×3508).
#   2. Open it in any image editor and hover over each fill-in box.
#   3. Record top-left (x, y) and size (w, h) for each field.
#   4. Replace the values below and restart the server.
COVER_FIELDS: dict[str, tuple[int, int, int, int]] = {
    "Emplid":          (485,  992,  693,  125),
    "Course Code":     (617,  1610, 597,  131),
    "number of pages": (130,  701,  733,  241),
}

# Placeholder regions for the MCQ answer-sheet layout — calibrate against a
# real MCQ scan the same way as COVER_FIELDS above before relying on these.
MCQ_COVER_FIELDS: dict[str, tuple[int, int, int, int]] = {
    "Emplid":      (0, 0, 100, 100),
    "Course Code": (0, 0, 100, 100),
}