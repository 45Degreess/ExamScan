"""The ExamScan web layer: HTTP routing, run workflow, and the server loop.

Hardware-agnostic. Entry points build the camera, servos and stepper, then
hand them to `serve()` — `main.py` with real hardware, `devserver.py` with fakes.
"""

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from config import CONFIG_PATH, ConfigError, ConfigManager
from runs import RunError, RunManager, decorate_manifest, resolve_project_path


class BusyError(RuntimeError):
    pass


def get_local_ip():
    result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
    for ip in result.stdout.strip().split():
        if not ip.startswith("127"):
            return ip
    return "localhost"


class ExamScanHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            parts = path.strip("/").split("/") if path != "/" else []

            if path == "/":
                self._send_json(
                    200,
                    {
                        "service": "examscan",
                        "stream": "/stream",
                        "health": "/api/health",
                    },
                )
            elif path == "/stream":
                self._serve_stream()
            elif path == "/api/health":
                self._send_json(200, self.server.health())
            elif path == "/api/config":
                self._send_bytes(
                    200,
                    self.server.config_manager.read_bytes(),
                    "application/toml",
                    "config.toml",
                )
            elif path == "/api/runs":
                self._send_json(200, {"runs": self.server.run_manager.list_runs()})
            elif len(parts) == 3 and parts[:2] == ["api", "runs"]:
                self._send_json(200, self.server.run_manager.public_manifest(parts[2]))
            elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "archive":
                run_manager = self.server.run_manager
                self._send_bytes(
                    200,
                    run_manager.build_archive(parts[2]),
                    "application/zip",
                    run_manager.archive_filename(parts[2]),
                )
            else:
                self._send_error(404, "not found")
        except (ConfigError, RunError, ValueError) as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            if path == "/api/runs":
                self._handle_create_run()
                return

            if len(parts) != 4 or parts[:2] != ["api", "runs"]:
                self._send_error(404, "not found")
                return

            run_id, action = parts[2], parts[3]
            if action == "capture":
                self._handle_capture(run_id)
            elif action == "page-turn":
                self._handle_page_turn(run_id)
            elif action == "scan-step":
                self._handle_scan_step(run_id)
            elif action == "auto-scan":
                self._handle_auto_scan(run_id)
            elif action == "complete":
                self._handle_complete(run_id)
            else:
                self._send_error(404, "not found")
        except BusyError as exc:
            self._send_error(409, str(exc))
        except (ConfigError, RunError, ValueError) as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def _handle_create_run(self):
        manifest = self.server.run_manager.create_run()
        self._send_json(201, self._run_response(manifest))

    def _handle_capture(self, run_id):
        manifest = self.server.capture_page_locked(run_id)
        self._send_json(200, self._run_response(manifest))

    def _handle_page_turn(self, run_id):
        self.server.page_turn_locked(run_id)
        self._send_json(200, {"ok": True, "run_id": run_id})

    def _handle_scan_step(self, run_id):
        manifest = self.server.scan_step_locked(run_id)
        self._send_json(200, self._run_response(manifest))

    def _handle_auto_scan(self, run_id):
        data = self._read_json(default={})
        manifest = self.server.auto_scan_locked(run_id, data.get("pages"))
        self._send_json(200, self._run_response(manifest))

    def _handle_complete(self, run_id):
        manifest = self.server.complete_run_locked(run_id)
        self._send_json(200, self._run_response(manifest))

    def do_PUT(self):
        try:
            if urlparse(self.path).path != "/api/config":
                self._send_error(404, "not found")
                return
            body = self._read_body()
            response = self.server.replace_config(body)
            self._send_json(200, response)
        except ConfigError as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def _serve_stream(self):
        camera = self.server.camera
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while camera.streaming:
                with camera.stream_output.condition:
                    if not camera.stream_output.condition.wait(timeout=1.0):
                        continue
                    frame = camera.stream_output.frame
                if frame is None:
                    continue
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except Exception:
            pass

    def _send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self._send_bytes(status, body, "application/json")

    def _send_error(self, status, message):
        self._send_json(status, {"error": message})

    def _send_bytes(self, status, body, content_type, filename=None):
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self):
        config = self.server.config["server"]
        if not config["cors_enabled"]:
            return
        origin = self.headers.get("Origin")
        allowed = config["cors_allowed_origins"]
        if "*" in allowed:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1:
            return b""
        return self.rfile.read(length)

    def _read_json(self, default=None):
        body = self._read_body()
        if not body:
            return default
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON body") from exc

    def _run_response(self, manifest):
        return decorate_manifest(dict(manifest))


class ExamScanServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        config_manager,
        config,
        camera,
        servos,
        stepper,
        handler=ExamScanHandler,
    ):
        super().__init__(address, handler)
        self.config_manager = config_manager
        self.config = config
        self.camera = camera
        self.servos = servos
        self.stepper = stepper
        self.run_manager = RunManager(config)
        self.operation_lock = threading.Lock()
        self.operation_name = None
        self.config_restart_required = False

    def health(self):
        return {
            "ok": True,
            "active_run_id": self.run_manager.active_run_id,
            "busy": self.operation_lock.locked(),
            "operation": self.operation_name,
            "streaming": self.camera.streaming,
            "config_restart_required": self.config_restart_required,
        }

    def run_locked(self, operation_name, callback, *args):
        if not self.operation_lock.acquire(blocking=False):
            raise BusyError(f"hardware is busy with {self.operation_name}")
        self.operation_name = operation_name
        try:
            return callback(*args)
        finally:
            self.operation_name = None
            self.operation_lock.release()

    def capture_page_locked(self, run_id):
        return self.run_locked("capture", self.capture_page, run_id)

    def page_turn_locked(self, run_id):
        return self.run_locked("page-turn", self._page_turn_for, run_id)

    def scan_step_locked(self, run_id):
        return self.run_locked("scan-step", self.scan_step, run_id)

    def auto_scan_locked(self, run_id, pages):
        return self.run_locked("auto-scan", self.auto_scan, run_id, pages)

    def complete_run_locked(self, run_id):
        return self.run_locked("complete", self.run_manager.complete_run, run_id)

    def _record_failure(self, run_id, operation, exc):
        try:
            self.run_manager.add_error(run_id, operation, str(exc))
        except RunError:
            pass  # run directory gone; the original exception still propagates

    def capture_page(self, run_id):
        image_path = self.run_manager.next_capture_path(run_id)
        try:
            self.camera.capture_file(image_path)
        except Exception as exc:
            self._record_failure(run_id, "capture", exc)
            raise
        return self.run_manager.add_page(run_id, image_path)

    def _page_turn_for(self, run_id):
        try:
            self.page_turn()
        except Exception as exc:
            self._record_failure(run_id, "page-turn", exc)
            raise

    def page_turn(self):
        """Clamp down, arm down, stepper out, clamp up, arm up, stepper back.

        The clamp lifts partway through the stepper's outward run, so that run
        is split into two halves with the lift between them. The stepper then
        goes all the way back once the arm is clear, so the wheel ends every
        page turn where it started and cannot creep round.
        """
        servo_config = self.config["servos"]["page_drop"]
        clamp_config = self.config["servos"]["page_clamp_left"]
        workflow = self.config["workflow"]
        motor_config = self.config["motor"]
        page_drop_servo = self.servos.page_drop
        clamp_servo = self.servos.page_clamp_left

        # Split in steps, not degrees: two half-degree moves can round to one
        # step more or less than the single full move, which would leave the
        # wheel short of where it started. Splitting the step count is exact.
        total_steps = round(
            motor_config["steps_per_rev"] * motor_config["default_degrees"] / 360
        )
        first_steps = total_steps // 2
        second_steps = total_steps - first_steps
        clockwise = motor_config["default_clockwise"]

        clamp_servo.set_angle(
            clamp_config["down_angle"],
            settle_time=clamp_config["default_settle_time"],
        )
        time.sleep(workflow["clamp_down_pause"])

        page_drop_servo.set_angle(
            servo_config["down_angle"],
            settle_time=servo_config["default_settle_time"],
        )
        time.sleep(workflow["servo_down_pause"])

        self.stepper.move_steps(first_steps, clockwise=clockwise)

        clamp_servo.set_angle(
            clamp_config["up_angle"],
            settle_time=clamp_config["default_settle_time"],
        )
        time.sleep(workflow["clamp_up_pause"])

        self.stepper.move_steps(second_steps, clockwise=clockwise)
        time.sleep(workflow["stepper_pause"])

        page_drop_servo.set_angle(
            servo_config["up_angle"],
            settle_time=servo_config["default_settle_time"],
        )
        time.sleep(workflow["servo_up_pause"])

        self.stepper.move_steps(total_steps, clockwise=not clockwise)

    def scan_step(self, run_id):
        manifest = self.capture_page(run_id)
        self._page_turn_for(run_id)
        return manifest

    def auto_scan(self, run_id, pages=None):
        if pages is None:
            pages = self.config["workflow"]["default_pages"]
        if isinstance(pages, bool) or not isinstance(pages, int) or pages < 1:
            raise ValueError("pages must be a positive integer")
        manifest = None
        for index in range(pages):
            manifest = self.capture_page(run_id)
            if index < pages - 1:
                self._page_turn_for(run_id)
        return self.run_manager.complete_run(run_id)

    def replace_config(self, body):
        old_config = self.config
        new_config = self.config_manager.save_uploaded(body)
        applied_live = self.config_manager.applied_live_sections(old_config, new_config)
        restart_required = self.config_manager.restart_required(old_config, new_config)

        if hasattr(self.servos, "reload_config"):
            self.servos.reload_config(old_config["servos"], new_config["servos"])
        self.config = new_config
        self.run_manager.set_config(new_config)
        self.config_restart_required = self.config_restart_required or restart_required

        return {
            "ok": True,
            "restart_required": restart_required,
            "applied_live": applied_live,
        }


def prepare_directories(config):
    resolve_project_path(config["paths"]["runs_dir"]).mkdir(parents=True, exist_ok=True)


def load_config():
    config_manager = ConfigManager(CONFIG_PATH)
    config = config_manager.load()
    prepare_directories(config)
    return config_manager, config


def serve(
    config_manager,
    config,
    camera,
    servos,
    stepper,
    banner=None,
    handler=ExamScanHandler,
):
    """Start the server and block until Ctrl+C, then clean up the hardware.

    Real and fake hardware expose the same stop()/cleanup() contract, so every
    entry point shares this loop. `handler` lets the demo entry point serve a
    page at / while inheriting the rest of the routing.
    """
    address = (config["server"]["host"], config["server"]["port"])
    server = ExamScanServer(
        address,
        config_manager,
        config,
        camera,
        servos,
        stepper,
        handler=handler,
    )

    if banner:
        print(banner)
    print(f"API listening on http://{get_local_ip()}:{config['server']['port']}")
    print("Running... press Ctrl+C to quit")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        server.server_close()
        camera.stop()
        servos.cleanup()
        # Last, so its pull-up restore lands after everything else is released.
        stepper.cleanup()
        print("Stopped.")
