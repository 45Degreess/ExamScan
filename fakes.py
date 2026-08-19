"""Stand-in hardware shared by the test suite and the dev server.

Nothing here touches a camera or a GPIO pin, so the real HTTP API can be run
and exercised on a machine with no scanner attached.
"""

import io
import shutil
import threading
import time

from PIL import Image, ImageDraw

from hardware.camera import StreamOutput

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

    def move_degrees(self, degrees, clockwise=True, keep_enabled=False):
        self.moves.append(
            {"degrees": degrees, "clockwise": clockwise, "keep_enabled": keep_enabled}
        )
        self.enabled = keep_enabled
        if self.delay:
            time.sleep(degrees / 360.0)

    def move_steps(self, steps, clockwise=True, step_delay=None, keep_enabled=False):
        self.moves.append(
            {"steps": steps, "clockwise": clockwise, "keep_enabled": keep_enabled}
        )
        self.enabled = keep_enabled
        if self.delay:
            time.sleep(steps / 200.0)

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

    def set_angle(self, degrees, settle_time=0.4, slow_start=False, hold=False):
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
