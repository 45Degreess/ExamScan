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

from .config import CONFIG_PATH, ConfigError, ConfigManager
from .drivers.vision import ObstructionError
from .runs import RunError, RunManager, decorate_manifest, resolve_project_path


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
            elif action == "scan-last-page":
                self._handle_scan_last_page(run_id)
            elif action == "auto-scan":
                self._handle_auto_scan(run_id)
            elif action == "complete":
                self._handle_complete(run_id)
            else:
                self._send_error(404, "not found")
        except (BusyError, ObstructionError) as exc:
            self._send_error(409, str(exc))
        except (ConfigError, RunError, ValueError) as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_DELETE(self):
        try:
            if urlparse(self.path).path != "/api/runs":
                self._send_error(404, "not found")
                return
            response = self.server.delete_runs_locked()
            self._send_json(200, {"ok": True, **response})
        except BusyError as exc:
            self._send_error(409, str(exc))
        except (RunError, ValueError) as exc:
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

    def _handle_scan_last_page(self, run_id):
        manifest = self.server.scan_last_page_locked(run_id)
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
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
        obstruction=None,
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
        self.obstruction = obstruction
        # Sequence state, so /health can report a pause before any turn has run.
        self._phases = []
        self._held = {}
        self._fan_duty = 0
        self._paused_phase = None
        self.run_manager = RunManager(config)
        self.operation_lock = threading.Lock()
        self.operation_name = None
        self.config_restart_required = False

    def health(self):
        hand_detection = self._hand_detection()
        return {
            "ok": True,
            "active_run_id": self.run_manager.active_run_id,
            "busy": self.operation_lock.locked(),
            "operation": self.operation_name,
            "streaming": self.camera.streaming,
            "config_restart_required": self.config_restart_required,
            "hand_present": hand_detection.get("hand_present"),
            "hand_detection": hand_detection,
            "paused": self._paused_phase is not None,
            "paused_phase": self._paused_phase,
        }

    def _hand_present(self):
        return self._hand_detection().get("hand_present")

    def _hand_detection(self):
        if self.obstruction is None:
            return {
                "mode": "disabled",
                "state": "disabled",
                "hand_present": None,
                "safe_to_move": True,
                "reason": None,
                "clear_count": None,
                "clear_frames": None,
                "palm_score": None,
                "presence_score": None,
                "confirmed_hands": 0,
                "inference_ms": None,
                "source_width": None,
                "source_height": None,
                "region": None,
                "bed_roi": None,
                "effective_fps": None,
                "exposure_time_us": None,
                "analogue_gain": None,
                "debug_overlay": False,
                "checked_at_age_seconds": None,
                "error": None,
            }
        status = getattr(self.obstruction, "status", None)
        if isinstance(status, dict):
            keys = (
                "mode",
                "state",
                "hand_present",
                "safe_to_move",
                "reason",
                "clear_count",
                "clear_frames",
                "palm_score",
                "presence_score",
                "confirmed_hands",
                "inference_ms",
                "source_width",
                "source_height",
                "region",
                "bed_roi",
                "effective_fps",
                "exposure_time_us",
                "analogue_gain",
                "debug_overlay",
                "checked_at_age_seconds",
                "error",
            )
            return {key: status.get(key) for key in keys}
        present = not self.obstruction.is_clear()
        return {
            "mode": "legacy",
            "state": "candidate" if present else "clear",
            "hand_present": present,
            "safe_to_move": not present,
            "reason": "possible hand is in the scan area" if present else None,
            "clear_count": None,
            "clear_frames": None,
            "palm_score": None,
            "presence_score": None,
            "confirmed_hands": 0,
            "inference_ms": None,
            "source_width": None,
            "source_height": None,
            "region": None,
            "bed_roi": None,
            "effective_fps": None,
            "exposure_time_us": None,
            "analogue_gain": None,
            "debug_overlay": False,
            "checked_at_age_seconds": None,
            "error": None,
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

    def scan_last_page_locked(self, run_id):
        return self.run_locked("scan-last-page", self.scan_last_page, run_id)

    def auto_scan_locked(self, run_id, pages):
        return self.run_locked("auto-scan", self.auto_scan, run_id, pages)

    def complete_run_locked(self, run_id):
        return self.run_locked("complete", self.run_manager.complete_run, run_id)

    def delete_runs_locked(self):
        return self.run_locked("delete-runs", self.run_manager.delete_all_runs)

    def _record_failure(self, run_id, operation, exc):
        try:
            self.run_manager.add_error(run_id, operation, str(exc))
        except RunError:
            pass  # run directory gone; the original exception still propagates

    def capture_page(self, run_id):
        image_path = self.run_manager.next_capture_path(run_id)
        try:
            # Detection runs continuously, including while no run is active.
            # Waiting here keeps a hand out of the captured page and gives
            # direct API clients the same fail-closed behaviour as the UI.
            if self.obstruction is not None:
                self.obstruction.wait_until_clear()
            self.camera.capture_file(image_path)
        except Exception as exc:
            self._record_failure(run_id, "capture", exc)
            raise
        return self.run_manager.add_page(run_id, image_path)

    def _page_turn_for(self, run_id, delay_big_clamp_release=False):
        try:
            self.page_turn(delay_big_clamp_release=delay_big_clamp_release)
        except Exception as exc:
            self._record_failure(run_id, "page-turn", exc)
            raise

    # ---- resumable phase building blocks -------------------------------
    #
    # Every sub-step takes an abort callable and returns True only if it
    # finished. Anything that stops early leaves enough state behind to pick up
    # the remainder later: re-running a whole move instead would repeat the part
    # already done, which on a stepper means turning the wheel twice as far.

    def _paced(self, seconds):
        """An interruptible settle, resuming with whatever time is left."""
        left = {"t": seconds}

        def run(abort):
            end = time.monotonic() + left["t"]
            while True:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    left["t"] = 0
                    return True
                if abort():
                    left["t"] = remaining
                    return False
                time.sleep(min(0.02, remaining))

        return run

    def _stepper_move(self, motor, steps, clockwise, keep_enabled=False):
        left = {"n": steps}

        def run(abort):
            done = motor.move_steps(
                left["n"],
                clockwise=clockwise,
                keep_enabled=keep_enabled,
                abort_check=abort,
            )
            left["n"] -= done
            return left["n"] == 0

        return run

    def _parallel_move(self, first, second):
        """Both wheels at once, each tracking its own remainder.

        An exception inside a Thread does not reach the joining thread, so a
        motor that failed would be swallowed and the turn would report success
        on a page that never moved. Results are captured and re-raised.
        """
        def run(abort):
            done, errors = {}, []

            def guard(name, move):
                def body():
                    try:
                        done[name] = move(abort)
                    except Exception as exc:
                        errors.append(exc)

                return body

            threads = [
                threading.Thread(target=guard("first", first)),
                threading.Thread(target=guard("second", second)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            if errors:
                raise errors[0]
            return all(done.values())

        return run

    def _servo_move(self, servo, angle, servo_config, hold=False):
        def run(abort):
            reached = servo.set_angle(
                angle,
                settle_time=servo_config["default_settle_time"],
                hold=hold,
                abort_check=abort,
            )
            if reached:
                if hold:
                    self._held[servo] = (angle, servo_config)
                else:
                    self._held.pop(servo, None)
            return reached

        return run

    def _seat_and_hold(self, servo, servo_config):
        """Seat a clamp at contact, then ease back and hold just off the stop.

        Holding hard against a stop the servo cannot reach leaves it stalled -
        it buzzes, warms up, and drags the supply down. Easing back to
        hold_angle keeps the clamp's pressure at an angle it can actually hold.
        """
        seat = self._servo_move(servo, servo_config["contact_angle"], servo_config)
        if not servo_config["use_hold"]:
            def release(abort):
                servo.detach()
                return True

            return [seat, release]
        return [
            seat,
            self._servo_move(
                servo, servo_config["hold_angle"], servo_config, hold=True
            ),
        ]

    def _refresh_hold(self, servo, servo_config):
        """Restart a clamp's hold cut-off without changing its setpoint."""
        def run(abort):
            if not servo_config["use_hold"]:
                return True
            reached = servo.set_angle(
                servo_config["hold_angle"],
                settle_time=0,
                hold=True,
                abort_check=abort,
            )
            if reached:
                self._held[servo] = (servo_config["hold_angle"], servo_config)
            return reached

        return run

    def _fan(self, percent):
        def run(abort):
            self.fan.set_duty(percent)
            self._fan_duty = percent
            return True

        return run

    @staticmethod
    def _steps_for(motor_config, degrees):
        return round(motor_config["steps_per_rev"] * degrees / 360)

    def _reassert_holds(self):
        """Re-command every held servo so its cut-off timer restarts.

        max_hold_seconds exists so a servo cannot sit stalled forever, but a
        pause of unknown length would trip it and let the clamps go limp -
        dropping the page mid-turn, silently, because the timer detaches rather
        than raising.
        """
        for servo, (angle, servo_config) in list(self._held.items()):
            servo.set_angle(
                angle,
                settle_time=0,
                hold=True,
            )

    def _pause_for_obstruction(self, number, label):
        """Stop dead, wait for the area to clear, then restore and carry on.

        Motion stops; static holds do not. A stationary energised stepper is not
        a hazard and letting go of it would drop the wheel position the resume
        depends on, so the steppers stay live. The fan does stop - spinning
        blades are the actual danger, and it is the only thing that keeps moving
        on its own once commanded.
        """
        self._paused_phase = f"{number}/{len(self._phases)} ({label})"
        was_running = self._fan_duty
        self._next_reassert = time.monotonic()
        if was_running:
            self.fan.set_duty(0)

        print(f"!! HAND DETECTED - paused at phase {self._paused_phase}")
        print("   waiting for the scan area to clear...", flush=True)
        stopped_at = self._paused_phase
        try:
            self.obstruction.wait_until_clear(on_wait=self._keep_holds_alive)
        except ObstructionError as exc:
            self._release_everything()
            raise ObstructionError(
                f"{exc} - page turn stopped at phase {stopped_at}; check the "
                f"mechanism before retrying"
            ) from exc
        finally:
            self._paused_phase = None

        if was_running:
            self.fan.set_duty(was_running)
        print(f"-> area clear, resuming phase {number}/{len(self._phases)} ({label})",
              flush=True)

    def _keep_holds_alive(self):
        """Re-assert holds on a cadence comfortably inside their cut-off."""
        cutoffs = [
            servo_config["max_hold_seconds"]
            for _, servo_config in self._held.values()
        ]
        gap = max(0.5, (min(cutoffs) if cutoffs else 10.0) / 2)
        now = time.monotonic()
        if now >= self._next_reassert:
            self._reassert_holds()
            self._next_reassert = now + gap

    def _release_everything(self):
        """Safe state after giving up: nothing powered, nothing pressing."""
        try:
            self.fan.set_duty(0)
            self._fan_duty = 0
        finally:
            for motor in (self.stepper, self.stepper2):
                try:
                    motor.disable()
                except Exception:
                    pass
            for servo in list(self._held):
                try:
                    servo.detach()
                except Exception:
                    pass
            self._held.clear()

    def page_turn(self, delay_big_clamp_release=False):
        """The sixteen-phase page turn, guarded throughout.
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
        m2_preposition = self._steps_for(
            m2_config, m2_config["preposition_degrees"]
        )
        m2_first_remainder = m2_first - m2_preposition
        m2_shared = self._steps_for(m2_config, m2_config["shared_degrees"])
        m2_return = m2_first + m2_shared
        m1_home = m1_first - self._steps_for(m1_config, m1_config["return_short_degrees"])
        m2_home = m2_return - self._steps_for(m2_config, m2_config["return_short_degrees"])

        m1_cw = m1_config["default_clockwise"]
        m2_cw = m2_config["default_clockwise"]
        pace = workflow["motor_pause"]

        self._held = {}
        self._fan_duty = 0
        self._paused_phase = None

        preposition_steps = []
        if m2_preposition:
            preposition_steps.extend([
                self._stepper_move(self.stepper2, m2_preposition, m2_cw),
                self._paced(pace),
            ])
        phase11_steps = []
        if m2_first_remainder:
            phase11_steps.extend([
                self._stepper_move(self.stepper2, m2_first_remainder, m2_cw),
                self._paced(pace),
            ])

        second_small_clamp = []
        if delay_big_clamp_release:
            # The delayed release extends the active hold. Reissue the same
            # setpoint before the remaining motor legs so the servo's safety
            # timer cannot let the clamp go limp early.
            second_small_clamp.append(self._refresh_hold(big, big_config))
        second_small_clamp.extend(
            self._seat_and_hold(small, small_config)
            + [self._paced(workflow["clamp_down_pause"])]
        )
        big_clamp_up = [
            self._servo_move(big, big_config["up_angle"], big_config),
            self._paced(workflow["clamp_up_pause"]),
        ]

        common_phases = [
            ("small clamp down", self._seat_and_hold(small, small_config)
                + [self._paced(workflow["small_clamp_hold_seconds"])]),
            ("fan up to speed", [self._fan(fan_config["duty_pct"]),
                                 self._paced(fan_config["spinup_seconds"])]),
            ("arm down", [self._servo_move(arm, arm_config["down_angle"], arm_config),
                          self._paced(workflow["servo_down_pause"])]),
            ("big clamp down", self._seat_and_hold(big, big_config)
                + [self._paced(workflow["clamp_down_pause"])]),
            ("small clamp up", [self._servo_move(small, small_config["up_angle"], small_config),
                                self._paced(workflow["clamp_up_pause"])]),
            ("motor 1 out", [self._stepper_move(self.stepper, m1_first, m1_cw, keep_enabled=True),
                             self._paced(pace)]),
            ("motor 2 pre-position", preposition_steps),
            ("arm up", [self._servo_move(arm, arm_config["up_angle"], arm_config),
                        self._paced(workflow["servo_up_pause"])]),
            ("fan off", [self._fan(0)]),
        ]

        if workflow["turn_sequence"] == "motor2_only":
            motor1_home_phase = ("motor 1 home", [
                self._stepper_move(self.stepper, m1_first, not m1_cw),
                self._paced(pace),
            ])
            second_small_phase = (
                "small clamp down again", second_small_clamp
            )
            motor2_only_before_release = [
                second_small_phase,
            ]
            motor2_only_forward = [
                ("motor 2 out remainder", phase11_steps),
                ("motor 2 continuation", [
                    self._stepper_move(self.stepper2, m2_shared, m2_cw),
                    self._paced(pace),
                ]),
            ]
            motor2_only_return = [
                ("motor 2 home", [
                    self._stepper_move(self.stepper2, m2_home, not m2_cw),
                    self._paced(pace),
                ]),
                ("small clamp off", [
                    self._servo_move(small, small_config["up_angle"], small_config),
                    self._paced(workflow["clamp_up_pause"]),
                ]),
            ]
            if delay_big_clamp_release:
                self._phases = (
                    common_phases
                    + motor2_only_before_release
                    + motor2_only_forward
                    + [("big clamp up", big_clamp_up)]
                    + [motor1_home_phase]
                    + motor2_only_return
                )
            else:
                self._phases = (
                    common_phases
                    + [motor1_home_phase, second_small_phase]
                    + [("big clamp up", big_clamp_up)]
                    + motor2_only_forward
                    + motor2_only_return
                )
        else:
            shared_before_release = [
                ("small clamp down again", second_small_clamp),
            ]
            shared_forward = [
                ("motor 2 out remainder", phase11_steps),
                ("both wheels together", [
                    self._parallel_move(
                        self._stepper_move(
                            self.stepper, m1_shared, m1_cw, keep_enabled=True
                        ),
                        self._stepper_move(self.stepper2, m2_shared, m2_cw),
                    ),
                    self._paced(pace),
                ]),
            ]
            shared_return = [
                ("motor 2 home", [
                    self._stepper_move(self.stepper2, m2_home, not m2_cw),
                    self._paced(pace),
                ]),
                ("motor 1 back and small clamp off", [
                    self._stepper_move(
                        self.stepper, m1_shared, not m1_cw, keep_enabled=True
                    ),
                    self._paced(pace),
                    self._servo_move(small, small_config["up_angle"], small_config),
                    self._paced(workflow["clamp_up_pause"]),
                ]),
                ("motor 1 home", [
                    self._stepper_move(self.stepper, m1_home, not m1_cw)
                ]),
            ]
            if delay_big_clamp_release:
                self._phases = (
                    common_phases
                    + shared_before_release
                    + shared_forward
                    + [("big clamp up", big_clamp_up)]
                    + shared_return
                )
            else:
                self._phases = (
                    common_phases
                    + shared_before_release
                    + [("big clamp up", big_clamp_up)]
                    + shared_forward
                    + shared_return
                )

        abort = (
            self.obstruction.obstructed
            if self.obstruction is not None
            else lambda: False
        )
        try:
            for index, (label, steps) in enumerate(self._phases, start=1):
                for step in steps:
                    while not step(abort):
                        self._pause_for_obstruction(index, label)
        finally:
            # Whatever happened, the fan does not keep running.
            self.fan.set_duty(0)
            self._fan_duty = 0
            self._paused_phase = None

    def scan_step(self, run_id):
        manifest = self.capture_page(run_id)
        self._page_turn_for(run_id)
        return manifest

    def scan_last_page(self, run_id):
        manifest = self.capture_page(run_id)
        self._page_turn_for(run_id, delay_big_clamp_release=True)
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
    obstruction=None,
    banner=None,
    handler=ExamScanHandler,
):
    """Start the server and block until Ctrl+C, then clean up the hardware.

    Real and fake hardware expose the same stop()/cleanup() contract, so every
    entry point shares this loop. `handler` lets the Rig UI entry point serve
    a page at / while inheriting the rest of the routing.
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
        obstruction,
        handler=handler,
    )

    if obstruction is not None:
        obstruction.start()

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
        if obstruction is not None:
            obstruction.stop()
        # Drives the fan back to 0 and drops the pigpio connection.
        fan.cleanup()
        stepper.cleanup()
        stepper2.cleanup()
        print("Stopped.")
