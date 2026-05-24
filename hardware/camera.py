from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
import io
import json
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
CAPTURE_DIR = Path(__file__).parent / "captures"
LENS_POSITION = 0.97
PREVIEW_SIZE = (1920, 1080)
CAPTURE_SIZE = (4608, 2592)
FRAME_RATE = 30


class StreamOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = threading.Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            self._serve_index()
        elif self.path.startswith("/stream"):
            self._serve_stream()
        elif self.path == "/capture":
            self._handle_capture()

    def _serve_index(self):
        content = (STATIC_DIR / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_stream(self):
        server = self.server
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while server.streaming:
                with server.stream_output.condition:
                    if not server.stream_output.condition.wait(timeout=1.0):
                        continue
                    frame = server.stream_output.frame
                if frame is None:
                    continue
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except Exception:
            pass

    def _handle_capture(self):
        server = self.server
        with server.capture_lock:
            server.capture_count += 1
            filename = f"{date.today().isoformat()}_{server.capture_count:03d}.jpg"

        print(f"Capturing {filename}...")
        try:
            server.streaming = False
            with server.stream_output.condition:
                server.stream_output.condition.notify_all()
            time.sleep(0.2)

            server.picam2.stop_recording()
            time.sleep(0.2)

            server.picam2.configure(server.capture_config)
            server.picam2.start()
            time.sleep(0.5)
            server.picam2.capture_file(CAPTURE_DIR / filename)
            server.picam2.stop()
            time.sleep(0.2)

            server.picam2.configure(server.camera_config)
            server.picam2.start_recording(MJPEGEncoder(), FileOutput(server.stream_output))
            server.streaming = True

            print(f"Saved {filename}")
            self._send_json(200, {"filename": filename, "count": server.capture_count})

            time.sleep(2)
            server.motor.move_degrees(360)

        except Exception as e:
            print(f"Capture error: {e}")
            self._recover(server)
            self._send_json(500, {"error": str(e)})

    def _recover(self, server):
        try:
            server.picam2.stop()
        except Exception:
            pass
        try:
            server.picam2.configure(server.camera_config)
            server.picam2.start_recording(MJPEGEncoder(), FileOutput(server.stream_output))
            server.streaming = True
        except Exception as e:
            print(f"Recovery failed: {e}")

    def _send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CameraServer(HTTPServer):
    def __init__(self, server_address, picam2, camera_config, capture_config, motor):
        super().__init__(server_address, StreamHandler)
        self.picam2 = picam2
        self.camera_config = camera_config
        self.capture_config = capture_config
        self.motor = motor
        self.stream_output = StreamOutput()
        self.capture_count = 0
        self.capture_lock = threading.Lock()
        self.streaming = True

    def process_request(self, request, client_address):
        thread = threading.Thread(
            target=self.process_request_thread,
            args=(request, client_address),
            daemon=True,
        )
        thread.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            pass
        finally:
            self.shutdown_request(request)


def make_camera():
    picam2 = Picamera2()

    camera_config = picam2.create_video_configuration(
        main={"size": PREVIEW_SIZE},
        buffer_count=6,
        controls={
            "FrameRate": FRAME_RATE,
            "FrameDurationLimits": (33333, 33333),
            "AfMode": 0,
            "LensPosition": LENS_POSITION,
        },
    )

    capture_config = picam2.create_still_configuration(
        main={"size": CAPTURE_SIZE}
    )

    return picam2, camera_config, capture_config
