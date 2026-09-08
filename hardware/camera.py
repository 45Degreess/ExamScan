from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
from picamera2 import Picamera2
import io
import threading
import time


class StreamOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = threading.Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class CameraController:
    def __init__(self, picam2, camera_config, capture_config, stream_output, config):
        self.picam2 = picam2
        self.camera_config = camera_config
        self.capture_config = capture_config
        self.stream_output = stream_output
        self.config = config
        self.streaming = True

    def start_recording(self):
        self.picam2.configure(self.camera_config)
        self.picam2.start_recording(MJPEGEncoder(), FileOutput(self.stream_output))
        time.sleep(self.config["recording_start_delay"])
        self.streaming = True

    def capture_file(self, path):
        print(f"Capturing {path.name}...")
        try:
            self.streaming = False
            with self.stream_output.condition:
                self.stream_output.condition.notify_all()
            time.sleep(self.config["capture_stop_delay"])

            self.picam2.stop_recording()
            time.sleep(self.config["capture_stop_delay"])

            self.picam2.configure(self.capture_config)
            self.picam2.start()
            time.sleep(self.config["capture_settle_delay"])
            self.picam2.capture_file(path)
            self.picam2.stop()
            time.sleep(self.config["capture_restart_delay"])

            self.picam2.configure(self.camera_config)
            self.picam2.start_recording(MJPEGEncoder(), FileOutput(self.stream_output))
            self.streaming = True
            print(f"Saved {path.name}")
        except Exception:
            self.recover()
            raise

    def recover(self):
        try:
            self.picam2.stop()
        except Exception:
            pass
        try:
            self.picam2.configure(self.camera_config)
            self.picam2.start_recording(MJPEGEncoder(), FileOutput(self.stream_output))
            self.streaming = True
        except Exception as exc:
            print(f"Recovery failed: {exc}")

    def stop(self):
        self.streaming = False
        with self.stream_output.condition:
            self.stream_output.condition.notify_all()
        try:
            self.picam2.stop_recording()
        except Exception:
            pass
        try:
            self.picam2.close()
        except Exception:
            pass


def make_camera(config):
    picam2 = Picamera2()
    preview_size = (config["preview_width"], config["preview_height"])
    capture_size = (config["capture_width"], config["capture_height"])
    frame_duration = round(1_000_000 / config["frame_rate"])

    camera_config = picam2.create_video_configuration(
        main={"size": preview_size},
        buffer_count=config["buffer_count"],
        controls={
            "FrameRate": config["frame_rate"],
            "FrameDurationLimits": (frame_duration, frame_duration),
            "AfMode": 0,
            "LensPosition": config["lens_position"],
        },
    )

    capture_config = picam2.create_still_configuration(
        main={"size": capture_size}
    )

    return picam2, camera_config, capture_config
