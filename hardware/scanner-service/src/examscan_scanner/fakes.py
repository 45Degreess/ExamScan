"""Stand-in hardware shared by the test suite and the dev server.

Nothing here touches a camera or a GPIO pin, so the real HTTP API can be run
and exercised on a machine with no scanner attached.
"""

import io
import shutil
import threading
import time

import numpy as np
from PIL import Image, ImageDraw

from .drivers.camera import StreamOutput
# The real class, not a lookalike - the HTTP layer catches this exact type
# to turn it into a 409, so a mirror here would silently fall through.
from .drivers.vision import ObstructionError



PREVIEW_SIZE = (960, 540)
FRAME_INTERVAL = 0.2


def _render(text, size=PREVIEW_SIZE):
    image = Image.new("RGB", size, color=(32, 36, 44))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, size[0] - 8, size[1] - 8), outline=(76, 201, 240), width=4)
    draw.text((32, 32), text, fill=(235, 238, 242))
    return image


def jpeg_bytes(text, size=PREVIEW_SIZE):
    buffer = io.BytesIO()
    _render(text, size).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeCamera:
    """Writes placeholder JPEGs instead of driving the Pi camera.

    Tests pass a ``sample_image`` to copy. The dev server passes nothing, so
    each capture gets an image labelled with its own filename, which makes a
    downloaded archive easy to eyeball.
    """

    def __init__(self, sample_image=None, delay=0):
        self.sample_image = sample_image
        self.delay = delay
        self.streaming = True
        self.stream_output = None
        self._stop = threading.Event()

    def start_streaming(self):
        """Push frames into a real StreamOutput so GET /stream works.

        Only the dev server calls this; tests leave stream_output as None.
        """
        self.stream_output = StreamOutput()
        threading.Thread(target=self._push_frames, daemon=True).start()

    def _push_frames(self):
        while not self._stop.is_set():
            if self.streaming:
                self.stream_output.write(
                    jpeg_bytes(f"ExamScan dev preview\n{time.strftime('%H:%M:%S')}")
                )
            time.sleep(FRAME_INTERVAL)

    def capture_array(self, name="lores"):
        # Shaped like Picamera2's YUV420 lores plane: height x 1.5, single
        # channel, which is what to_rgb() expects to convert.
        return np.zeros((810, 960), dtype=np.uint8)

    def capture_array_with_metadata(self, name="lores"):
        return self.capture_array(name), {
            "ExposureTime": 8000,
            "AnalogueGain": 1.0,
        }

    def capture_file(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.delay:
            time.sleep(self.delay)
        if self.sample_image is not None:
            shutil.copy2(self.sample_image, path)
        else:
            _render(f"ExamScan\n{path.name}").save(path, format="JPEG")

    def stop(self):
        self._stop.set()
        self.streaming = False


class FakeStepperMotor:
    """Records rotations. With delay=True it also takes time doing them."""

    def __init__(self, delay=False):
        self.delay = delay
        self.moves = []
        self.enabled = False

    def move_degrees(self, degrees, clockwise=True, keep_enabled=False, abort_check=None):
        self.moves.append(
            {"degrees": degrees, "clockwise": clockwise, "keep_enabled": keep_enabled}
        )
        self.enabled = keep_enabled
        if self.delay:
            time.sleep(degrees / 360.0)
        return degrees

    def move_steps(
        self,
        steps,
        clockwise=True,
        step_delay=None,
        keep_enabled=False,
        abort_check=None,
    ):
        done = steps
        if abort_check is not None:
            done = 0
            for _ in range(steps):
                if abort_check():
                    break
                done += 1
        self.moves.append(
            {
                "steps": done,
                "requested": steps,
                "clockwise": clockwise,
                "keep_enabled": keep_enabled,
            }
        )
        self.enabled = keep_enabled or done < steps
        if self.delay:
            time.sleep(done / 200.0)
        return done

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def cleanup(self):
        pass


class FakeServo:
    def __init__(self, delay=False):
        self.delay = delay
        self.angles = []
        self.held = False

    def set_angle(
        self,
        degrees,
        settle_time=0.4,
        slow_start=False,
        hold=False,
        abort_check=None,
    ):
        if abort_check is not None and abort_check():
            return False
        self.angles.append(
            {
                "degrees": degrees,
                "settle_time": settle_time,
                "slow_start": slow_start,
                "hold": hold,
            }
        )
        self.held = hold
        if self.delay:
            time.sleep(settle_time)
        return True

    def detach(self):
        self.held = False


class FakeFan:
    """Records duty changes. Starts at 0, like the real FanController does."""

    def __init__(self):
        self.duty_pct = 0
        self.duties = [0]

    def set_duty(self, percent):
        percent = max(0, min(100, float(percent)))
        self.duty_pct = percent
        self.duties.append(percent)
        return percent

    def read_rpm(self):
        return None

    def cleanup(self):
        self.set_duty(0)


class FakeObstructionMonitor:
    """Stands in for the camera-based gate, with the verdict set by hand.

    Set hand_present to make the page turn stop and wait; clear_after_polls says
    how many checks it takes before the area reads clear again, so a test can
    interrupt a turn at a chosen point and watch it resume.
    """

    def __init__(
        self,
        hand_present=False,
        obstruct_after_polls=None,
        clear_after_polls=None,
        wait_timeout_seconds=0.5,
    ):
        self.hand_present = hand_present
        # A hand appearing at a chosen poll, so a test can interrupt a specific
        # move rather than whichever phase happens to come first.
        self.obstruct_after_polls = obstruct_after_polls
        self.clear_after_polls = clear_after_polls
        self.wait_timeout_seconds = wait_timeout_seconds
        self.polls = 0
        self.waits = 0
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    @property
    def status(self):
        return {
            "mode": "fake",
            "state": "confirmed" if self.hand_present else "clear",
            "hand_present": self.hand_present,
            "safe_to_move": not self.hand_present,
            "reason": (
                "confirmed hand is in the scan area"
                if self.hand_present
                else None
            ),
            "clear_count": 0 if self.hand_present else 1,
            "clear_frames": 1,
            "score": None,
            "palm_score": None,
            "presence_score": 1.0 if self.hand_present else 0.0,
            "confirmed_hands": 1 if self.hand_present else 0,
            "inference_ms": 0.0,
            "source_width": 960,
            "source_height": 540,
            "region": "bed",
            "bed_roi": [0.0, 0.0, 1.0, 1.0],
            "effective_fps": 10.0,
            "exposure_time_us": 8000.0,
            "analogue_gain": 1.0,
            "debug_overlay": False,
            "checked_at_age_seconds": 0.0,
            "error": None,
        }

    def is_clear(self):
        self.polls += 1
        if (
            self.obstruct_after_polls is not None
            and self.polls >= self.obstruct_after_polls
        ):
            self.hand_present = True
            self.obstruct_after_polls = None
            self.clear_after_polls = self.polls + (self.clear_after_polls or 3)
        if (
            self.clear_after_polls is not None
            and self.polls >= self.clear_after_polls
        ):
            self.hand_present = False
        return not self.hand_present

    def obstructed(self):
        return not self.is_clear()

    def wait_until_clear(self, timeout=None, on_wait=None):
        self.waits += 1
        timeout = self.wait_timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while not self.is_clear():
            if time.monotonic() >= deadline:
                raise ObstructionError(
                    "scan area not clear: a hand is in the scan area"
                )
            if on_wait is not None:
                on_wait()
            time.sleep(0.01)


class FakeServoController:
    def __init__(self, delay=False):
        self.page_drop = FakeServo(delay=delay)
        self.page_clamp_big = FakeServo(delay=delay)
        self.page_clamp_small = FakeServo(delay=delay)
        self.reloads = []

    def reload_config(self, old_config, new_config):
        self.reloads.append({"old": old_config, "new": new_config})

    def cleanup(self):
        pass
