"""The ExamScan web layer: HTTP routing, run workflow, and the server loop.

Hardware-agnostic. Entry points build the camera, servos and stepper, then hand
them to `serve()` — `main.py` with real hardware, `devserver.py` with fakes.
"""

import json
import subprocess
import sys
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
        stepper2,
        fan,
        handler=ExamScanHandler,
    ):
        super().__init__(address, handler)
        self.config_manager = config_manager
        self.config = config
        self.camera = camera
        self.servos = servos
        self.stepper = stepper
        self.stepper2 = stepper2
        self.fan = fan
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

    def _seat_and_hold(self, servo, servo_config):
        """Seat a clamp at its contact angle, then hold just off the stop.

        Holding hard against a stop the servo cannot reach leaves it stalled -
        it buzzes, warms up, and drags the supply down. Easing back to
        hold_angle keeps the clamp's pressure at an angle it can actually hold.
        """
        settle = servo_config["default_settle_time"]
        servo.set_angle(servo_config["contact_angle"], settle_time=settle)
        if not servo_config["use_hold"]:
            servo.detach()
            return time.monotonic()
        servo.set_angle(servo_config["hold_angle"], settle_time=settle, hold=True)
        return time.monotonic()

    def _lift(self, servo, servo_config, held_since, name):
        """Lift a clamp, reporting a hold that outlasted its own cut-off.

        A hold past max_hold_seconds detaches on a timer rather than raising, so
        the clamp goes limp silently and _last_angle keeps claiming it is still
        down. Logging the overrun is the only way that surfaces.
        """
        if held_since is not None:
            elapsed = time.monotonic() - held_since
            if servo_config["use_hold"] and elapsed > servo_config["max_hold_seconds"]:
                print(
                    f"page-turn: {name} held {elapsed:.1f}s, past its "
                    f"{servo_config['max_hold_seconds']:g}s cut-off - it will "
                    f"have gone limp",
                    file=sys.stderr,
                )
        servo.set_angle(
            servo_config["up_angle"],
            settle_time=servo_config["default_settle_time"],
        )

    @staticmethod
    def _in_parallel(*moves):
        """Run motor moves at once, surfacing whatever they raise.

        An exception inside a Thread does not reach the joining thread, so a
        motor that failed would be swallowed and the page turn would report
        success on a page that never turned. Each result is captured and
        re-raised after the join.
        """
        errors = []

        def guard(move):
            def run():
                try:
                    move()
                except Exception as exc:
                    errors.append(exc)

            return run

        threads = [threading.Thread(target=guard(move)) for move in moves]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if errors:
            raise errors[0]

    @staticmethod
    def _steps_for(motor_config, degrees):
        return round(motor_config["steps_per_rev"] * degrees / 360)

    def page_turn(self):
        """The sixteen-phase page turn, as tuned in hardware/test_workflow.py.

        Small clamp down and hold, fan up to speed, arm down, big clamp takes
        over, then the two wheels trade the page between them and unwind.

        The wheels do NOT end where they started: each motor's final return
        stops return_short_degrees short, so a multi-page run walks them
        steadily round. Set return_short_degrees to 0 in config.toml for an
        exact round trip.
        """
        arm_config = self.config["servos"]["page_drop"]
        big_config = self.config["servos"]["page_clamp_big"]
        small_config = self.config["servos"]["page_clamp_small"]
        workflow = self.config["workflow"]
        fan_config = self.config["fan"]
        m1_config = self.config["motor"]
        m2_config = self.config["motor2"]

        arm = self.servos.page_drop
        big = self.servos.page_clamp_big
        small = self.servos.page_clamp_small

        # Split in steps, not degrees: two part-degree moves can round to one
        # step more or less than the single full move, which would leave a
        # wheel off by a step every page.
        m1_first = self._steps_for(m1_config, m1_config["page_turn_degrees"])
        m1_shared = self._steps_for(m1_config, m1_config["shared_degrees"])
        m2_first = self._steps_for(m2_config, m2_config["page_turn_degrees"])
        m2_shared = self._steps_for(m2_config, m2_config["shared_degrees"])
        m2_return = m2_first + m2_shared
        m1_home = m1_first - self._steps_for(m1_config, m1_config["return_short_degrees"])
        m2_home = m2_return - self._steps_for(m2_config, m2_config["return_short_degrees"])

        m1_cw = m1_config["default_clockwise"]
        m2_cw = m2_config["default_clockwise"]
        motor_pause = workflow["motor_pause"]

        # [1] Small clamp down and hold.
        small_held = self._seat_and_hold(small, small_config)
        time.sleep(workflow["small_clamp_hold_seconds"])

        try:
            # [2] Fan up, and give it time to reach speed before the arm lands.
            self.fan.set_duty(fan_config["duty_pct"])
            time.sleep(fan_config["spinup_seconds"])

            # [3] Arm down. No hold - it rests on the page.
            arm.set_angle(
                arm_config["down_angle"],
                settle_time=arm_config["default_settle_time"],
            )
            time.sleep(workflow["servo_down_pause"])

            # [4] Big clamp takes the grip.
            big_held = self._seat_and_hold(big, big_config)
            time.sleep(workflow["clamp_down_pause"])

            # [5] Small clamp out of the way.
            self._lift(small, small_config, small_held, "page_clamp_small")
            small_held = None
            time.sleep(workflow["clamp_up_pause"])

            # [6] Motor 1 out, staying energised so it holds the page against
            # the clamp for the rest of the sequence.
            self.stepper.move_steps(m1_first, clockwise=m1_cw, keep_enabled=True)
            time.sleep(motor_pause)

            # [7] Arm clear, then [8] fan off - the page is captive now.
            self._lift(arm, arm_config, None, "page_drop")
            time.sleep(workflow["servo_up_pause"])
        finally:
            # Whatever went wrong above, the fan does not keep running.
            self.fan.set_duty(0)

        # [9] Small clamp back down to grip before the big one lets go.
        small_held = self._seat_and_hold(small, small_config)
        time.sleep(workflow["clamp_down_pause"])

        # [10] Big clamp releases.
        self._lift(big, big_config, big_held, "page_clamp_big")
        time.sleep(workflow["clamp_up_pause"])

        # [11] Motor 2 out to meet it.
        self.stepper2.move_steps(m2_first, clockwise=m2_cw)
        time.sleep(motor_pause)

        # [12] Both wheels carry the page together.
        self._in_parallel(
            lambda: self.stepper.move_steps(
                m1_shared, clockwise=m1_cw, keep_enabled=True
            ),
            lambda: self.stepper2.move_steps(m2_shared, clockwise=m2_cw),
        )
        time.sleep(motor_pause)

        # [13] Motor 2 home, [14] motor 1 unwinds the shared leg.
        self.stepper2.move_steps(m2_home, clockwise=not m2_cw)
        time.sleep(motor_pause)
        self.stepper.move_steps(m1_shared, clockwise=not m1_cw, keep_enabled=True)
        time.sleep(motor_pause)

        # [15] Small clamp off, then [16] motor 1 home and finally de-energised.
        self._lift(small, small_config, small_held, "page_clamp_small")
        time.sleep(workflow["clamp_up_pause"])
        self.stepper.move_steps(m1_home, clockwise=not m1_cw)

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
    stepper2,
    fan,
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
        stepper2,
        fan,
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
        # Drives the fan back to 0 and drops the pigpio connection.
        fan.cleanup()
        # Last, so their pull-up restore lands after everything else is
        # released.
        stepper.cleanup()
        stepper2.cleanup()
        print("Stopped.")
