from __future__ import annotations

import os

# Base URL of the runs API that serves page archives at
# GET {RUNS_API_BASE_URL}/api/runs/{id}/archive.
# TODO: update to the real runs-API host once deployed/known.
RUNS_API_BASE_URL = os.environ.get("RUNS_API_BASE_URL", "http://10.42.0.1:8000")

A4_WIDTH  = 2480   # 210 mm at 300 DPI
A4_HEIGHT = 3508   # 297 mm at 300 DPI

# overlay onto raw Pi captures (before detect_document) to
# hide rig hardware visible at the frame edges.
RIG_OVERLAY_PATH = os.path.join(os.path.dirname(__file__), "assets", "rig_overlay_v7.png")

A3_WIDTH  = A4_WIDTH * 2   # 4960 px
A3_HEIGHT = A4_HEIGHT      # 3508 px

# Crop coordinates defined on the A4_WIDTH × A4_HEIGHT canonical image.
COVER_FIELDS: dict[str, tuple[int, int, int, int]] = {
    "Emplid":          (518, 1019, 633, 67),
    "Course Code":     (617,  1610, 597,  131),
    "number of pages": (130,  701,  733,  241),
}

# Pixels trimmed from each side of the 6 separator lines
EMPLID_PADDING = 28

# Placeholder regions for the MCQ answer-sheet layout
# TODO: MCQ sheet was not implemented and this stayed a placeholder
MCQ_COVER_FIELDS: dict[str, tuple[int, int, int, int]] = {
    "Emplid":      (106, 117, 274, 41),
    "Course Code": (140, 164, 240, 37),
}

# Two regions red-pen total mark might be written
MARK_FIELDS: list[tuple[int, int, int, int]] = [
    (883, 343, 734, 588),
    (1410, 1139, 1005, 1456),
]