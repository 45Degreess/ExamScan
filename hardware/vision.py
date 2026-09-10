"""Fail-closed hand detection over the camera's low-resolution stream.

The Pi 4 cannot import MediaPipe's Python wheel because that binary requires
AES CPU instructions. This module runs the two official Hand Landmarker models
directly through LiteRT: palm localization, weighted NMS, a rotated hand crop,
and 21-point landmark verification.

Vision is an additional obstruction gate, not safety-rated protective
equipment. A palm candidate that cannot be landmark-confirmed is deliberately
still treated as an obstruction.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, replace

import cv2
import numpy as np
from ai_edge_litert.interpreter import Interpreter


PALM_INPUT_SIZE = 192
LANDMARK_INPUT_SIZE = 224
PALM_KEYPOINTS = 7
NMS_IOU_THRESHOLD = 0.3


class ObstructionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DetectionResult:
    """A compact verdict plus diagnostics; landmark coordinates stay local."""

    state: str
    palm_score: float
    presence_score: float | None
    confirmed_hands: int
    inference_ms: float
    landmarks: tuple[tuple[tuple[float, float, float], ...], ...] = ()

    @property
    def hand_present(self):
        return self.state in {"confirmed", "candidate"}


@dataclass(frozen=True)
class DetectionCrop:
    """A source-frame crop and the geometry needed to project results back."""

    image: np.ndarray
    left: int
    top: int
    right: int
    bottom: int
    source_width: int
    source_height: int


def crop_detection_region(rgb, roi):
    """Crop a normalized [left, top, right, bottom] region from an RGB frame."""
    source_height, source_width = rgb.shape[:2]
    left = max(0, min(source_width - 1, math.floor(float(roi[0]) * source_width)))
    top = max(0, min(source_height - 1, math.floor(float(roi[1]) * source_height)))
    right = max(left + 1, min(source_width, math.ceil(float(roi[2]) * source_width)))
    bottom = max(top + 1, min(source_height, math.ceil(float(roi[3]) * source_height)))
    return DetectionCrop(
        image=rgb[top:bottom, left:right],
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        source_width=source_width,
        source_height=source_height,
    )


def project_landmarks_from_crop(landmarks, crop):
    """Project normalized crop landmarks back to normalized full-frame space."""
    crop_width = crop.right - crop.left
    crop_height = crop.bottom - crop.top
    return tuple(
        tuple(
            (
                (crop.left + point[0] * crop_width) / crop.source_width,
                (crop.top + point[1] * crop_height) / crop.source_height,
                point[2],
            )
            for point in hand
        )
        for hand in landmarks
    )


def project_result_from_crop(result, crop):
    if not result.landmarks:
        return result
    return replace(
        result,
        landmarks=project_landmarks_from_crop(result.landmarks, crop),
    )


@dataclass(frozen=True)
class _Anchor:
    x_center: float
    y_center: float
    width: float = 1.0
    height: float = 1.0


@dataclass(frozen=True)
class _Letterbox:
    image: np.ndarray
    scale: float
    left: int
    top: int
    source_width: int
    source_height: int

    def point_to_source(self, x, y):
        source_x = (x * PALM_INPUT_SIZE - self.left) / self.scale
        source_y = (y * PALM_INPUT_SIZE - self.top) / self.scale
        return source_x / self.source_width, source_y / self.source_height


@dataclass(frozen=True)
class _PalmDetection:
    score: float
    box: tuple[float, float, float, float]
    keypoints: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class _HandRoi:
    center_x: float
    center_y: float
    size: float
    rotation: float


def _sigmoid(value):
    return 1.0 / (1.0 + np.exp(-np.clip(value, -100.0, 100.0)))


def _calculate_scale(min_scale, max_scale, stride_index, num_strides):
    if num_strides == 1:
        return (min_scale + max_scale) * 0.5
    return min_scale + (max_scale - min_scale) * stride_index / (num_strides - 1)


def generate_palm_anchors():
    """Generate the official 2,016 fixed-size palm-detector anchors."""
    strides = (8, 16, 16, 16)
    min_scale, max_scale = 0.1484375, 0.75
    anchors = []
    layer = 0
    while layer < len(strides):
        same_stride_layers = []
        while (
            layer + len(same_stride_layers) < len(strides)
            and strides[layer + len(same_stride_layers)] == strides[layer]
        ):
            same_stride_layers.append(layer + len(same_stride_layers))

        anchors_per_cell = 0
        for index in same_stride_layers:
            _calculate_scale(min_scale, max_scale, index, len(strides))
            # One aspect-ratio-1 anchor and one interpolated-scale anchor.
            anchors_per_cell += 2

        stride = strides[layer]
        feature_size = math.ceil(PALM_INPUT_SIZE / stride)
        for y in range(feature_size):
            for x in range(feature_size):
                for _ in range(anchors_per_cell):
                    anchors.append(
                        _Anchor(
                            x_center=(x + 0.5) / feature_size,
                            y_center=(y + 0.5) / feature_size,
                        )
                    )
        layer += len(same_stride_layers)

    if len(anchors) != 2016:
        raise RuntimeError(f"expected 2016 palm anchors, generated {len(anchors)}")
    return tuple(anchors)


def _intersection_over_union(first, second):
    ax1, ay1, ax2, ay2 = first.box
    bx1, by1, bx2, by2 = second.box
    intersection_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    intersection_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_w * intersection_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0.0 else 0.0


def weighted_non_max_suppression(detections, threshold=NMS_IOU_THRESHOLD):
    """MediaPipe-style weighted NMS for overlapping palm detections."""
    remaining = sorted(detections, key=lambda item: item.score, reverse=True)
    selected = []
    while remaining:
        reference = remaining[0]
        overlaps, next_remaining = [], []
        for detection in remaining:
            if _intersection_over_union(reference, detection) > threshold:
                overlaps.append(detection)
            else:
                next_remaining.append(detection)

        total = sum(item.score for item in overlaps)
        box = tuple(
            sum(item.box[index] * item.score for item in overlaps) / total
            for index in range(4)
        )
        keypoints = tuple(
            (
                sum(item.keypoints[k][0] * item.score for item in overlaps) / total,
                sum(item.keypoints[k][1] * item.score for item in overlaps) / total,
            )
            for k in range(PALM_KEYPOINTS)
        )
        selected.append(_PalmDetection(reference.score, box, keypoints))
        remaining = next_remaining
    return selected


def _normalize_radians(angle):
    return angle - 2.0 * math.pi * math.floor((angle + math.pi) / (2.0 * math.pi))


def hand_roi_from_detection(detection, image_width, image_height):
    """Create MediaPipe's shifted 2.6x square hand crop from a palm."""
    xmin, ymin, xmax, ymax = detection.box
    box_width = (xmax - xmin) * image_width
    box_height = (ymax - ymin) * image_height
    center_x = (xmin + xmax) * 0.5 * image_width
    center_y = (ymin + ymax) * 0.5 * image_height

    wrist = detection.keypoints[0]
    middle_mcp = detection.keypoints[2]
    vector_x = (middle_mcp[0] - wrist[0]) * image_width
    vector_y = (middle_mcp[1] - wrist[1]) * image_height
    rotation = _normalize_radians(math.pi / 2.0 - math.atan2(-vector_y, vector_x))

    # RectTransformationCalculator: shift_y=-0.5 before square/scale.
    shift_y = -0.5 * box_height
    center_x += -shift_y * math.sin(rotation)
    center_y += shift_y * math.cos(rotation)
    size = max(box_width, box_height) * 2.6
    return _HandRoi(center_x, center_y, max(size, 1.0), rotation)


def _roi_source_corners(roi):
    half = roi.size * 0.5
    local = np.array(
        [[-half, -half], [half, -half], [half, half], [-half, half]],
        dtype=np.float32,
    )
    cosine, sine = math.cos(roi.rotation), math.sin(roi.rotation)
    rotation = np.array([[cosine, -sine], [sine, cosine]], dtype=np.float32)
    return local @ rotation.T + np.array([roi.center_x, roi.center_y], dtype=np.float32)


def extract_rotated_roi(rgb, roi, output_size=LANDMARK_INPUT_SIZE):
    """Warp a rotated source-image square into an upright model input."""
    source = _roi_source_corners(roi).astype(np.float32)
    edge = float(output_size - 1)
    target = np.array([[0, 0], [edge, 0], [edge, edge], [0, edge]], np.float32)
    source_to_target = cv2.getPerspectiveTransform(source, target)
    target_to_source = cv2.getPerspectiveTransform(target, source)
    crop = cv2.warpPerspective(
        rgb,
        source_to_target,
        (output_size, output_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    return crop, target_to_source


class HandDetector:
    """Detect palms, verify them with landmarks, and return a safe verdict."""

    def __init__(
        self,
        model_path,
        min_confidence=0.3,
        mode="palm",
        landmark_model_path=None,
        min_presence_confidence=0.5,
        min_candidate_presence_confidence=0.01,
        max_hands=2,
        inference_threads=4,
    ):
        if mode not in {"full", "palm"}:
            raise ValueError("mode must be 'full' or 'palm'")
        if mode == "full" and not landmark_model_path:
            raise ValueError("landmark_model_path is required in full mode")

        self.mode = mode
        self.min_confidence = min_confidence
        self.min_presence_confidence = min_presence_confidence
        self.min_candidate_presence_confidence = min_candidate_presence_confidence
        self.max_hands = max_hands
        self._anchors = generate_palm_anchors()

        self._interpreter = Interpreter(
            model_path=str(model_path), num_threads=inference_threads
        )
        self._interpreter.allocate_tensors()
        self._input = self._interpreter.get_input_details()[0]
        if tuple(self._input["shape"]) != (1, PALM_INPUT_SIZE, PALM_INPUT_SIZE, 3):
            raise ValueError(f"unexpected palm model input shape: {self._input['shape']}")
        outputs = self._interpreter.get_output_details()
        self._box_index = next(d["index"] for d in outputs if d["shape"][-1] == 18)
        self._score_index = next(d["index"] for d in outputs if d["shape"][-1] == 1)

        self._landmark_interpreter = None
        if mode == "full":
            self._landmark_interpreter = Interpreter(
                model_path=str(landmark_model_path), num_threads=inference_threads
            )
            self._landmark_interpreter.allocate_tensors()
            self._landmark_input = self._landmark_interpreter.get_input_details()[0]
            if tuple(self._landmark_input["shape"]) != (
                1,
                LANDMARK_INPUT_SIZE,
                LANDMARK_INPUT_SIZE,
                3,
            ):
                raise ValueError(
                    f"unexpected landmark model input shape: {self._landmark_input['shape']}"
                )
            outputs_by_name = {
                detail["name"]: detail["index"]
                for detail in self._landmark_interpreter.get_output_details()
            }
            required = {"Identity", "Identity_1", "Identity_2", "Identity_3"}
            if set(outputs_by_name) != required:
                raise ValueError(
                    "unexpected landmark model outputs: "
                    + ", ".join(sorted(outputs_by_name))
                )
            self._landmarks_index = outputs_by_name["Identity"]
            self._presence_index = outputs_by_name["Identity_1"]
            self._handedness_index = outputs_by_name["Identity_2"]
            self._world_landmarks_index = outputs_by_name["Identity_3"]

    @classmethod
    def from_config(cls, config):
        return cls(
            model_path=config["model_path"],
            min_confidence=config["min_confidence"],
            mode=config.get("mode", "palm"),
            landmark_model_path=config.get("landmark_model_path"),
            min_presence_confidence=config.get("min_presence_confidence", 0.5),
            min_candidate_presence_confidence=config.get(
                "min_candidate_presence_confidence", 0.01
            ),
            max_hands=config.get("max_hands", 2),
            inference_threads=config.get("inference_threads", 4),
        )

    def _letterbox(self, rgb):
        height, width = rgb.shape[:2]
        scale = PALM_INPUT_SIZE / max(height, width)
        new_h, new_w = int(round(height * scale)), int(round(width * scale))
        resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
        square = np.zeros((PALM_INPUT_SIZE, PALM_INPUT_SIZE, 3), dtype=resized.dtype)
        top, left = (PALM_INPUT_SIZE - new_h) // 2, (PALM_INPUT_SIZE - new_w) // 2
        square[top : top + new_h, left : left + new_w] = resized
        return _Letterbox(square, scale, left, top, width, height)

    def _palm_inference(self, rgb):
        letterbox = self._letterbox(rgb)
        frame = letterbox.image.astype(np.float32) / 255.0
        self._interpreter.set_tensor(self._input["index"], frame[None])
        self._interpreter.invoke()
        boxes = self._interpreter.get_tensor(self._box_index)[0]
        logits = self._interpreter.get_tensor(self._score_index)[0, :, 0]
        scores = _sigmoid(logits)
        return letterbox, boxes, scores

    def score(self, rgb):
        """Maximum palm confidence, retained for existing callers/tests."""
        _, _, scores = self._palm_inference(rgb)
        return float(scores.max())

    def _decode_palms(self, raw_boxes, scores, letterbox):
        decoded = []
        for index in np.flatnonzero(scores >= self.min_confidence):
            raw = raw_boxes[index]
            anchor = self._anchors[int(index)]
            # reverse_output_order=true in MediaPipe's HandDetectorGraph.
            y_center = raw[0] / PALM_INPUT_SIZE * anchor.height + anchor.y_center
            x_center = raw[1] / PALM_INPUT_SIZE * anchor.width + anchor.x_center
            height = raw[2] / PALM_INPUT_SIZE * anchor.height
            width = raw[3] / PALM_INPUT_SIZE * anchor.width
            xmin, ymin = letterbox.point_to_source(
                x_center - width * 0.5, y_center - height * 0.5
            )
            xmax, ymax = letterbox.point_to_source(
                x_center + width * 0.5, y_center + height * 0.5
            )
            keypoints = []
            for keypoint in range(PALM_KEYPOINTS):
                offset = 4 + keypoint * 2
                point_y = raw[offset] / PALM_INPUT_SIZE + anchor.y_center
                point_x = raw[offset + 1] / PALM_INPUT_SIZE + anchor.x_center
                keypoints.append(letterbox.point_to_source(point_x, point_y))
            decoded.append(
                _PalmDetection(
                    float(scores[index]),
                    (xmin, ymin, xmax, ymax),
                    tuple(keypoints),
                )
            )
        return weighted_non_max_suppression(decoded)[: self.max_hands]

    def _landmark_hand(self, rgb, detection):
        height, width = rgb.shape[:2]
        roi = hand_roi_from_detection(detection, width, height)
        crop, target_to_source = extract_rotated_roi(rgb, roi)
        tensor = crop.astype(np.float32) / 255.0
        self._landmark_interpreter.set_tensor(self._landmark_input["index"], tensor[None])
        self._landmark_interpreter.invoke()

        presence = float(
            self._landmark_interpreter.get_tensor(self._presence_index).reshape(-1)[0]
        )
        handedness = float(
            self._landmark_interpreter.get_tensor(self._handedness_index).reshape(-1)[0]
        )
        image_landmarks = self._landmark_interpreter.get_tensor(
            self._landmarks_index
        ).reshape(21, 3)
        world_landmarks = self._landmark_interpreter.get_tensor(
            self._world_landmarks_index
        ).reshape(21, 3)

        points = image_landmarks[:, :2].astype(np.float32).reshape(1, -1, 2)
        source_points = cv2.perspectiveTransform(points, target_to_source)[0]
        projected = tuple(
            (
                float(point[0] / width),
                float(point[1] / height),
                float(raw[2] / (LANDMARK_INPUT_SIZE * 0.4)),
            )
            for point, raw in zip(source_points, image_landmarks)
        )

        cosine, sine = math.cos(roi.rotation), math.sin(roi.rotation)
        projected_world = tuple(
            (
                float(cosine * point[0] - sine * point[1]),
                float(sine * point[0] + cosine * point[1]),
                float(point[2]),
            )
            for point in world_landmarks
        )
        return presence, handedness, projected, projected_world

    def detect(self, rgb, on_candidate=None):
        started = time.perf_counter()
        letterbox, raw_boxes, scores = self._palm_inference(rgb)
        palm_score = float(scores.max())

        if self.mode == "palm":
            state = "candidate" if palm_score >= self.min_confidence else "clear"
            if state == "candidate" and on_candidate is not None:
                on_candidate(palm_score, (time.perf_counter() - started) * 1000.0)
            return DetectionResult(
                state, palm_score, None, 0, (time.perf_counter() - started) * 1000.0
            )

        palms = self._decode_palms(raw_boxes, scores, letterbox)
        if palms and on_candidate is not None:
            on_candidate(palm_score, (time.perf_counter() - started) * 1000.0)
        max_presence = None
        confirmed = 0
        all_landmarks = []
        for palm in palms:
            presence, _handedness, landmarks, _world = self._landmark_hand(rgb, palm)
            max_presence = presence if max_presence is None else max(max_presence, presence)
            if presence >= self.min_presence_confidence:
                confirmed += 1
                all_landmarks.append(landmarks)
                # The gate only needs proof that at least one hand is present.
                # A second candidate remains useful when the first fails, but
                # running it after confirmation only adds latency.
                break

        if confirmed:
            state = "confirmed"
        elif palms:
            state = "candidate"
        else:
            state = "clear"
        return DetectionResult(
            state=state,
            palm_score=palm_score,
            presence_score=max_presence,
            confirmed_hands=confirmed,
            inference_ms=(time.perf_counter() - started) * 1000.0,
            landmarks=tuple(all_landmarks),
        )

    def hand_present(self, rgb):
        return self.detect(rgb).hand_present

    def close(self):
        self._interpreter = None
        self._landmark_interpreter = None


class ObstructionMonitor:
    """Poll the camera and make only repeated clear readings actionable."""

    def __init__(
        self,
        camera,
        detector,
        poll_interval=0.1,
        clear_frames=5,
        stale_after_seconds=3.0,
        wait_timeout_seconds=30.0,
        stream_name="lores",
        target_interval=None,
        source_width=None,
        source_height=None,
        bed_roi=(0.0, 0.0, 1.0, 1.0),
        region_schedule=("bed", "bed", "full"),
        debug_overlay=False,
    ):
        self.camera = camera
        self.detector = detector
        self.poll_interval = poll_interval
        self.target_interval = (
            poll_interval if target_interval is None else target_interval
        )
        self.clear_frames = clear_frames
        self.stale_after_seconds = stale_after_seconds
        self.wait_timeout_seconds = wait_timeout_seconds
        self.stream_name = stream_name
        self.expected_source_width = source_width
        self.expected_source_height = source_height
        self.bed_roi = tuple(float(value) for value in bed_roi)
        self.region_schedule = tuple(region_schedule)
        self.debug_overlay = bool(debug_overlay)

        self._lock = threading.Lock()
        self._hand_present = None
        self._state = "unknown"
        self._palm_score = None
        self._presence_score = None
        self._confirmed_hands = 0
        self._inference_ms = None
        self._checked_at = None
        self._consecutive_clear = 0
        self._error = None
        self._source_width = source_width
        self._source_height = source_height
        self._region = "unknown"
        self._region_index = 0
        self._sample_times = deque(maxlen=20)
        self._effective_fps = None
        self._exposure_time_us = None
        self._analogue_gain = None
        self._last_metadata_at = None
        self._thread = None
        self._stop = threading.Event()

    @classmethod
    def from_config(cls, camera, detector, config):
        return cls(
            camera=camera,
            detector=detector,
            poll_interval=config["poll_interval"],
            target_interval=config.get("target_interval", config["poll_interval"]),
            source_width=config.get("source_width"),
            source_height=config.get("source_height"),
            bed_roi=config.get("bed_roi", (0.0, 0.0, 1.0, 1.0)),
            region_schedule=config.get("region_schedule", ("bed", "bed", "full")),
            debug_overlay=config.get("debug_overlay", False),
            clear_frames=config["clear_frames"],
            stale_after_seconds=config["stale_after_seconds"],
            wait_timeout_seconds=config["wait_timeout_seconds"],
        )

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.detector.close()

    @property
    def status(self):
        with self._lock:
            checked_at = self._checked_at
            age = None if checked_at is None else time.monotonic() - checked_at
            state = self._state
            present = self._hand_present
            clear_count = self._consecutive_clear
            reason = None
            if self._error is not None:
                state, present = "error", True
                reason = f"camera or detector error: {self._error}"
            elif checked_at is None:
                reason = "no camera reading yet"
            elif age is not None and age > self.stale_after_seconds:
                state, present = "stale", True
                reason = f"last camera reading was {age:.1f}s ago"
            elif present:
                detail = (
                    "confirmed hand"
                    if state == "confirmed"
                    else "possible hand (palm candidate)"
                )
                reason = f"{detail} is in the scan area"
            elif clear_count < self.clear_frames:
                reason = "waiting for a steady clear reading"
            return {
                "mode": getattr(self.detector, "mode", "unknown"),
                "state": state,
                "hand_present": present,
                "safe_to_move": reason is None,
                "reason": reason,
                "clear_count": clear_count,
                "clear_frames": self.clear_frames,
                "score": self._palm_score,
                "palm_score": self._palm_score,
                "presence_score": self._presence_score,
                "confirmed_hands": self._confirmed_hands,
                "inference_ms": self._inference_ms,
                "source_width": self._source_width,
                "source_height": self._source_height,
                "region": self._region,
                "bed_roi": list(self.bed_roi),
                "effective_fps": self._effective_fps,
                "exposure_time_us": self._exposure_time_us,
                "analogue_gain": self._analogue_gain,
                "debug_overlay": self.debug_overlay,
                "checked_at_age_seconds": age,
                "error": self._error,
            }

    def _next_region(self):
        region = self.region_schedule[self._region_index % len(self.region_schedule)]
        self._region_index += 1
        return region

    def _record_sample(self, sampled_at, width, height, region, metadata):
        with self._lock:
            self._source_width = width
            self._source_height = height
            self._region = region
            self._sample_times.append(sampled_at)
            if len(self._sample_times) >= 2:
                elapsed = self._sample_times[-1] - self._sample_times[0]
                if elapsed > 0:
                    self._effective_fps = (len(self._sample_times) - 1) / elapsed
            if (
                self._last_metadata_at is None
                or sampled_at - self._last_metadata_at >= 1.0
            ):
                exposure = metadata.get("ExposureTime")
                gain = metadata.get("AnalogueGain")
                self._exposure_time_us = (
                    None if exposure is None else float(exposure)
                )
                self._analogue_gain = None if gain is None else float(gain)
                self._last_metadata_at = sampled_at

    def _publish_candidate(self, palm_score, inference_ms):
        with self._lock:
            self._error = None
            self._state = "candidate"
            self._palm_score = palm_score
            self._presence_score = None
            self._confirmed_hands = 0
            self._inference_ms = inference_ms
            self._hand_present = True
            self._checked_at = time.monotonic()
            self._consecutive_clear = 0

    def _capture_latest(self):
        capture = getattr(self.camera, "capture_array_with_metadata", None)
        if capture is None:
            return self.camera.capture_array(self.stream_name), {}
        return capture(self.stream_name)

    def _run(self):
        while not self._stop.is_set():
            cycle_started = time.monotonic()
            if not self.camera.streaming:
                self._stop.wait(self.target_interval)
                continue
            try:
                frame, metadata = self._capture_latest()
                rgb = to_rgb(frame)
                height, width = rgb.shape[:2]
                if (
                    self.expected_source_width is not None
                    and self.expected_source_height is not None
                    and (width, height)
                    != (self.expected_source_width, self.expected_source_height)
                ):
                    raise ValueError(
                        "obstruction stream is "
                        f"{width}x{height}, expected "
                        f"{self.expected_source_width}x{self.expected_source_height}"
                    )
                region = self._next_region()
                roi = self.bed_roi if region == "bed" else (0.0, 0.0, 1.0, 1.0)
                crop = crop_detection_region(rgb, roi)
                self._record_sample(cycle_started, width, height, region, metadata)
                result = self.detector.detect(
                    crop.image,
                    on_candidate=self._publish_candidate,
                )
                result = project_result_from_crop(result, crop)
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
                    self._state = "error"
                    self._hand_present = True
                    self._consecutive_clear = 0
                remaining = self.target_interval - (time.monotonic() - cycle_started)
                self._stop.wait(max(0.0, remaining))
                continue

            present = result.hand_present
            with self._lock:
                self._error = None
                self._state = result.state
                self._palm_score = result.palm_score
                self._presence_score = result.presence_score
                self._confirmed_hands = result.confirmed_hands
                self._inference_ms = result.inference_ms
                self._hand_present = present
                self._checked_at = time.monotonic()
                self._consecutive_clear = 0 if present else self._consecutive_clear + 1
            remaining = self.target_interval - (time.monotonic() - cycle_started)
            self._stop.wait(max(0.0, remaining))

    def _verdict(self):
        with self._lock:
            checked_at, present = self._checked_at, self._hand_present
            clear_count, error = self._consecutive_clear, self._error
            state = self._state

        if error is not None:
            return False, f"camera or detector error: {error}"
        if checked_at is None:
            return False, "no camera reading yet"
        age = time.monotonic() - checked_at
        if age > self.stale_after_seconds:
            return False, f"last camera reading was {age:.1f}s ago"
        if present:
            detail = (
                "confirmed hand"
                if state == "confirmed"
                else "possible hand (palm candidate)"
            )
            return False, f"{detail} is in the scan area"
        if clear_count < self.clear_frames:
            return False, "waiting for a steady clear reading"
        return True, None

    def is_clear(self):
        return self._verdict()[0]

    def obstructed(self):
        return not self.is_clear()

    def wait_until_clear(self, timeout=None, on_wait=None):
        timeout = self.wait_timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while True:
            clear, reason = self._verdict()
            if clear:
                return
            if time.monotonic() >= deadline:
                raise ObstructionError(
                    f"scan area not clear after {timeout:g}s: {reason}"
                )
            if on_wait is not None:
                on_wait()
            time.sleep(self.poll_interval)


def to_rgb(frame):
    """Picamera2's lores stream is YUV420; the model wants RGB."""
    if frame.ndim == 3:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_YUV420p2RGB)
