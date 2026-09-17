from __future__ import annotations

import os

# Base URL of the runs API that serves page archives at
# GET {RUNS_API_BASE_URL}/api/runs/{id}/archive.
# TODO: update to the real runs-API host once deployed/known.
# Overridable via the RUNS_API_BASE_URL env var — used by
# `make collect-runs` (software/Makefile) to point at a local fake-Pi server
# instead of real hardware.
RUNS_API_BASE_URL = os.environ.get("RUNS_API_BASE_URL", "http://10.42.0.1:8000")

A4_WIDTH  = 2480   # 210 mm at 300 DPI
A4_HEIGHT = 3508   # 297 mm at 300 DPI

# BGRA overlay composited onto raw Pi captures (before detect_document) to
# hide rig hardware visible at the frame edges. Opaque border, transparent
# hole over the page/background region. See apply_rig_overlay/load_rig_overlay
# in processing.py.
RIG_OVERLAY_PATH = os.path.join(os.path.dirname(__file__), "assets", "rig_overlay_v7.png")

A3_WIDTH  = A4_WIDTH * 2   # 4960 px
A3_HEIGHT = A4_HEIGHT      # 3508 px

# Crop coordinates defined on the A4_WIDTH × A4_HEIGHT canonical image.
# HOW TO CALIBRATE FOR YOUR WORKBOOK:
#   1. POST a sample cover photo to /scan and save the PNG (already 2480×3508).
#   2. Open it in any image editor and hover over each fill-in box.
#   3. Record top-left (x, y) and size (w, h) for each field.
#   4. Replace the values below and restart the server.
COVER_FIELDS: dict[str, tuple[int, int, int, int]] = {
    "Emplid":          (518, 1019, 633, 67),
    "Course Code":     (617,  1610, 597,  131),
    "number of pages": (130,  701,  733,  241),
}

# Pixels trimmed from each side of the 6 internal separator lines when
# splitting COVER_FIELDS["Emplid"] into 7 individual digit crops.
EMPLID_PADDING = 28

# Placeholder regions for the MCQ answer-sheet layout — calibrate against a
# real MCQ scan the same way as COVER_FIELDS above before relying on these.
MCQ_COVER_FIELDS: dict[str, tuple[int, int, int, int]] = {
    "Emplid":      (106, 117, 274, 41),
    "Course Code": (140, 164, 240, 37),
}

# Two regions (on the cover page's canonical A4 image) where the examiner's
# red-pen total mark might be written — both are always checked, and the
# highest number found across either wins. Placeholder — calibrate against a
# real marked cover page the same way as COVER_FIELDS above before relying
# on these.
MARK_FIELDS: list[tuple[int, int, int, int]] = [
    (883, 343, 734, 588),
    (1410, 1139, 1005, 1456),
]