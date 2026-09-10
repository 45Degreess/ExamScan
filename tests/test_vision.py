"""The hand detector and the gate it feeds.

The detector tests run the real model against a real photograph. They are the
only place the normalisation is pinned down: feeding the model [-1, 1] instead
of [0, 1] saturates every logit, so a blank frame scores 1.0 and the gate jams
shut on a rig that is working perfectly. A test that only ever asserts "no hand
in a blank frame" would pass happily in that state.
"""

import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from hardware.vision import (
    DetectionResult,
    HandDetector,
    ObstructionError,
    ObstructionMonitor,
    _PalmDetection,
    crop_detection_region,
    generate_palm_anchors,
    project_landmarks_from_crop,
    weighted_non_max_suppression,
)


MODEL = Path(__file__).resolve().parents[1] / "models" / "hand_detector.tflite"
LANDMARK_MODEL = (
    Path(__file__).resolve().parents[1]
    / "models"
    / "hand_landmarks_detector.tflite"
)
HAND_PHOTO = Path(__file__).parent / "data" / "hand.jpg"


@pytest.fixture(scope="module")
def detector():
    return HandDetector(MODEL, min_confidence=0.5)


@pytest.fixture(scope="module")
def full_detector():
    detector = HandDetector(
        MODEL,
        min_confidence=0.3,
        mode="full",
        landmark_model_path=LANDMARK_MODEL,
        min_presence_confidence=0.5,
        min_candidate_presence_confidence=0.01,
        max_hands=2,
        inference_threads=4,
    )
    yield detector
    detector.close()


def rgb(path):
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def test_detects_a_hand(detector):
    assert detector.hand_present(rgb(HAND_PHOTO))


def test_blank_frame_is_not_a_hand(detector):
    blank = np.full((480, 640, 3), 200, dtype=np.uint8)
    assert not detector.hand_present(blank)


def test_scores_separate_clearly(detector):
    """The gap is what makes a single threshold safe to pick.

    If these ever converge, min_confidence stops being meaningful and the whole
    layer needs rethinking rather than retuning.
    """
    blank = np.full((480, 640, 3), 200, dtype=np.uint8)
    assert detector.score(rgb(HAND_PHOTO)) - detector.score(blank) > 0.5


def test_letterboxing_keeps_a_wide_frame_detectable(detector):
    """A 16:9 frame must not be squashed into the square input.

    Padding rather than stretching is why a hand in a widescreen preview still
    reads as a hand.
    """
    hand = rgb(HAND_PHOTO)
    wide = np.zeros((360, 640, 3), dtype=np.uint8)
    scaled = cv2.resize(hand, (240, 360))
    wide[:, 200:440] = scaled
    assert detector.hand_present(wide)


def test_official_palm_anchor_layout_has_2016_entries():
    anchors = generate_palm_anchors()
    assert len(anchors) == 2016
    assert anchors[0].x_center == pytest.approx(0.5 / 24)
    assert anchors[-1].y_center == pytest.approx(11.5 / 12)


def test_weighted_nms_merges_overlapping_palms():
    points = tuple((0.5, 0.5) for _ in range(7))
    detections = [
        _PalmDetection(0.9, (0.1, 0.1, 0.5, 0.5), points),
        _PalmDetection(0.6, (0.12, 0.12, 0.52, 0.52), points),
        _PalmDetection(0.8, (0.6, 0.6, 0.9, 0.9), points),
    ]

    merged = weighted_non_max_suppression(detections)

    assert len(merged) == 2
    assert merged[0].score == pytest.approx(0.9)
    assert 0.1 < merged[0].box[0] < 0.12


def test_full_detector_confirms_the_real_hand(full_detector):
    result = full_detector.detect(rgb(HAND_PHOTO))

    assert result.state == "confirmed"
    assert result.confirmed_hands == 1
    assert result.presence_score >= 0.5
    assert len(result.landmarks) == 1
    assert len(result.landmarks[0]) == 21


def test_full_detector_clears_a_blank_frame(full_detector):
    blank = np.full((480, 640, 3), 200, dtype=np.uint8)
    result = full_detector.detect(blank)

    assert result.state == "clear"
    assert not result.hand_present
    assert result.confirmed_hands == 0


def test_low_landmark_presence_keeps_a_decoded_palm_obstructed(
    full_detector, monkeypatch
):
    palm = _PalmDetection(
        0.8,
        (0.2, 0.2, 0.8, 0.8),
        tuple((0.5, 0.5) for _ in range(7)),
    )
    monkeypatch.setattr(
        full_detector,
        "_palm_inference",
        lambda _rgb: (None, np.zeros((1, 18)), np.array([0.8])),
    )
    monkeypatch.setattr(full_detector, "_decode_palms", lambda *_args: [palm])
    monkeypatch.setattr(
        full_detector,
        "_landmark_hand",
        lambda *_args: (0.0, 0.0, tuple((0.5, 0.5, 0.0) for _ in range(21)), ()),
    )

    result = full_detector.detect(np.zeros((540, 960, 3), dtype=np.uint8))

    assert result.state == "candidate"
    assert result.hand_present
    assert result.presence_score == 0.0


def test_candidate_is_published_before_landmark_verification(full_detector, monkeypatch):
    palm = _PalmDetection(
        0.8,
        (0.2, 0.2, 0.8, 0.8),
        tuple((0.5, 0.5) for _ in range(7)),
    )
    monkeypatch.setattr(
        full_detector,
        "_palm_inference",
        lambda _rgb: (None, np.zeros((1, 18)), np.array([0.8])),
    )
    monkeypatch.setattr(full_detector, "_decode_palms", lambda *_args: [palm])

    def slow_landmarks(*_args):
        time.sleep(0.05)
        return 0.0, 0.0, tuple((0.5, 0.5, 0.0) for _ in range(21)), ()

    monkeypatch.setattr(full_detector, "_landmark_hand", slow_landmarks)
    published = []
    started = time.perf_counter()

    full_detector.detect(
        np.zeros((540, 960, 3), dtype=np.uint8),
        on_candidate=lambda *_args: published.append(time.perf_counter()),
    )

    assert len(published) == 1
    assert published[0] - started < 0.04


@pytest.mark.parametrize("variant", ["small", "blur", "dark", "rotated", "edge"])
def test_full_detector_blocks_degraded_hand_views(full_detector, variant):
    hand = rgb(HAND_PHOTO)
    if variant == "small":
        frame = np.full((480, 640, 3), 200, dtype=np.uint8)
        frame[120:360, 240:400] = cv2.resize(hand, (160, 240))
    elif variant == "blur":
        frame = cv2.GaussianBlur(hand, (15, 15), 0)
    elif variant == "dark":
        frame = (hand.astype(np.float32) * 0.35).astype(np.uint8)
    elif variant == "rotated":
        matrix = cv2.getRotationMatrix2D(
            (hand.shape[1] / 2, hand.shape[0] / 2), 30, 1
        )
        frame = cv2.warpAffine(hand, matrix, (hand.shape[1], hand.shape[0]))
    else:
        frame = np.full((480, 640, 3), 200, dtype=np.uint8)
        scaled = cv2.resize(hand, (240, 360))
        frame[60:420, :140] = scaled[:, 100:]

    assert full_detector.detect(frame).hand_present


def test_the_real_camera_offers_what_the_monitor_needs():
    """Guards the gap that let a stub pass while the real object could not.

    ObstructionMonitor was written against capture_array(), which lives on
    Picamera2, not CameraController - the stub below happily provided it and
    every test passed until it met real hardware.
    """
    from hardware.camera import CameraController
    from fakes import FakeCamera

    for cls in (CameraController, FakeCamera):
        assert callable(getattr(cls, "capture_array", None)), cls.__name__


def test_a_fake_camera_frame_converts_like_a_real_one():
    """FakeCamera must hand back the same YUV420 shape Picamera2 does."""
    from fakes import FakeCamera
    from hardware.vision import to_rgb

    rgb = to_rgb(FakeCamera().capture_array())
    assert rgb.shape == (540, 960, 3)


def test_crop_and_landmarks_project_back_to_the_source_frame():
    source = np.zeros((100, 200, 3), dtype=np.uint8)
    crop = crop_detection_region(source, (0.25, 0.2, 0.75, 0.8))
    landmarks = (((0.0, 0.0, 1.0), (1.0, 1.0, 2.0)),)

    projected = project_landmarks_from_crop(landmarks, crop)

    assert crop.image.shape == (60, 100, 3)
    assert projected[0][0] == pytest.approx((0.25, 0.2, 1.0))
    assert projected[0][1] == pytest.approx((0.75, 0.8, 2.0))


class StubCamera:
    def __init__(self, streaming=True):
        self.streaming = streaming
        self.frames = 0

    def capture_array(self, name):
        self.frames += 1
        return np.zeros((240, 320, 3), dtype=np.uint8)


class StubDetector:
    """Reports whatever the test tells it to, with no model involved."""

    def __init__(self, score=0.0, min_confidence=0.5):
        self.min_confidence = min_confidence
        self.next_score = score
        self.closed = False

    def score(self, rgb):
        return self.next_score

    def detect(self, rgb, on_candidate=None):
        present = self.next_score >= self.min_confidence
        if present and on_candidate is not None:
            on_candidate(self.next_score, 0.0)
        return DetectionResult(
            state="candidate" if present else "clear",
            palm_score=self.next_score,
            presence_score=None,
            confirmed_hands=0,
            inference_ms=0.0,
        )

    def close(self):
        self.closed = True


def monitor(camera=None, detector=None, **kwargs):
    kwargs.setdefault("poll_interval", 0.01)
    kwargs.setdefault("clear_frames", 2)
    kwargs.setdefault("stale_after_seconds", 1.0)
    kwargs.setdefault("wait_timeout_seconds", 0.5)
    return ObstructionMonitor(
        camera or StubCamera(), detector or StubDetector(), **kwargs
    )


def test_wait_returns_once_the_area_reads_clear():
    m = monitor()
    m.start()
    try:
        m.wait_until_clear(timeout=2.0)
    finally:
        m.stop()


def test_wait_raises_while_a_hand_is_present():
    m = monitor(detector=StubDetector(score=0.99))
    m.start()
    try:
        with pytest.raises(ObstructionError, match="hand"):
            m.wait_until_clear(timeout=0.3)
    finally:
        m.stop()


def test_wait_returns_when_the_hand_clears_mid_wait():
    stub = StubDetector(score=0.99)
    m = monitor(detector=stub)
    m.start()
    threading.Timer(0.15, lambda: setattr(stub, "next_score", 0.0)).start()
    try:
        m.wait_until_clear(timeout=3.0)
    finally:
        m.stop()


def test_a_stale_reading_is_never_clear():
    """A monitor that has stopped reporting must not read as an all-clear.

    This is the failure that would make the layer worse than not having it: a
    dead thread looks exactly like an empty scan bed.
    """
    m = monitor(stale_after_seconds=0.05)
    m.start()
    time.sleep(0.2)
    m.stop()  # thread gone, verdict now ages out
    time.sleep(0.15)
    with pytest.raises(ObstructionError, match="camera reading"):
        m.wait_until_clear(timeout=0.2)


def test_no_reading_at_all_is_never_clear():
    """Before the first frame there is no evidence the bed is empty."""
    m = monitor()  # never started
    with pytest.raises(ObstructionError, match="no camera reading yet"):
        m.wait_until_clear(timeout=0.1)


def test_a_failing_camera_is_never_clear():
    class Broken(StubCamera):
        def capture_array(self, name):
            raise RuntimeError("camera gone")

    m = monitor(camera=Broken())
    m.start()
    try:
        time.sleep(0.1)
        with pytest.raises(ObstructionError):
            m.wait_until_clear(timeout=0.2)
        assert "camera gone" in (m.status["error"] or "")
    finally:
        m.stop()


def test_one_clear_frame_is_not_enough():
    """Debounce: a single dropped detection must not open the gate."""
    m = monitor(clear_frames=5, poll_interval=0.05, wait_timeout_seconds=0.1)
    m.start()
    try:
        with pytest.raises(ObstructionError, match="steady"):
            m.wait_until_clear(timeout=0.06)
        status = m.status
        assert status["safe_to_move"] is False
        assert status["reason"] == "waiting for a steady clear reading"
        assert status["clear_count"] < status["clear_frames"]
    finally:
        m.stop()


def test_status_becomes_safe_only_after_the_clear_frame_debounce():
    m = monitor(clear_frames=3, poll_interval=0.01)
    m.start()
    try:
        m.wait_until_clear(timeout=1.0)
        status = m.status
        assert status["state"] == "clear"
        assert status["hand_present"] is False
        assert status["safe_to_move"] is True
        assert status["reason"] is None
        assert status["clear_count"] >= 3
        assert status["clear_frames"] == 3
    finally:
        m.stop()


def test_monitor_pauses_while_the_camera_is_capturing():
    """capture_file() reconfigures the camera, so lores is briefly absent.

    Polling through that window would error every frame; the monitor holds its
    last verdict instead.
    """
    camera = StubCamera(streaming=False)
    m = monitor(camera=camera)
    m.start()
    try:
        time.sleep(0.1)
        assert camera.frames == 0
    finally:
        m.stop()


def test_region_schedule_repeats_bed_bed_full():
    m = monitor(region_schedule=("bed", "bed", "full"))

    assert [m._next_region() for _ in range(7)] == [
        "bed",
        "bed",
        "full",
        "bed",
        "bed",
        "full",
        "bed",
    ]


def test_target_period_does_not_add_a_sleep_after_slow_inference():
    class SlowDetector(StubDetector):
        def detect(self, rgb, on_candidate=None):
            time.sleep(0.04)
            return super().detect(rgb, on_candidate=on_candidate)

    camera = StubCamera()
    m = monitor(
        camera=camera,
        detector=SlowDetector(),
        poll_interval=0.05,
        target_interval=0.05,
    )
    m.start()
    try:
        time.sleep(0.22)
    finally:
        m.stop()

    assert camera.frames >= 4


def test_monitor_reports_source_region_rate_and_metadata():
    class MetadataCamera(StubCamera):
        def capture_array_with_metadata(self, name):
            return self.capture_array(name), {
                "ExposureTime": 7000,
                "AnalogueGain": 1.5,
            }

    m = monitor(camera=MetadataCamera(), region_schedule=("full",))
    m.start()
    try:
        m.wait_until_clear(timeout=1.0)
        status = m.status
    finally:
        m.stop()

    assert status["source_width"] == 320
    assert status["source_height"] == 240
    assert status["region"] == "full"
    assert status["effective_fps"] > 0
    assert status["exposure_time_us"] == 7000.0
    assert status["analogue_gain"] == 1.5


def test_stop_closes_the_detector():
    stub = StubDetector()
    m = monitor(detector=stub)
    m.start()
    m.stop()
    assert stub.closed
