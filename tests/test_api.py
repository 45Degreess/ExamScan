import io
import threading
import time
import zipfile

import pytest
import tomli_w

from server import ExamScanHandler, ExamScanServer
from tests.conftest import (
    ApiClient,
    FakeCamera,
    FakeFan,
    FakeObstructionMonitor,
    FakeServoController,
    FakeStepperMotor,
)


def test_health_returns_json(api_client):
    response = api_client.get("/api/health")

    assert response.status == 200
    assert response.json["ok"] is True
    assert response.json["busy"] is False
    assert response.json["streaming"] is True


def test_config_download_and_upload(api_client, config_dict):
    downloaded = api_client.get("/api/config")

    assert downloaded.status == 200
    assert downloaded.headers["Content-Type"] == "application/toml"
    assert b"[server]" in downloaded.body

    rejected = api_client.put("/api/config", b"invalid = [")

    assert rejected.status == 400
    assert rejected.json["error"].startswith("invalid TOML")

    config_dict["workflow"]["servo_down_pause"] = 1.5
    accepted = api_client.put("/api/config", tomli_w.dumps(config_dict).encode("utf-8"))

    assert accepted.status == 200
    assert accepted.json["restart_required"] is False
    assert accepted.json["applied_live"] == ["workflow"]


def test_raw_hardware_endpoints_do_not_exist(api_client):
    for path in ("/api/motor/turn", "/api/servo/angle", "/api/dc-motor/forward"):
        response = api_client.post(path, {})

        assert response.status == 404
        assert response.json["error"] == "not found"


def test_run_capture_complete_and_download_archive(api_client):
    created = api_client.post("/api/runs")
    run_id = created.json["run_id"]

    assert created.status == 201
    assert created.json["page_count"] == 0

    for expected_count in (1, 2):
        captured = api_client.post(f"/api/runs/{run_id}/capture")

        assert captured.status == 200
        assert captured.json["page_count"] == expected_count
        assert captured.json["pages"][-1]["filename"] == f"page_{expected_count:03d}.jpg"

    completed = api_client.post(f"/api/runs/{run_id}/complete")

    assert completed.status == 200
    assert completed.json["status"] == "complete"
    assert completed.json["page_count"] == 2
    assert completed.json["archive_url"] == f"/api/runs/{run_id}/archive"
    assert "pdf" not in completed.json

    archive = api_client.get(completed.json["archive_url"])

    assert archive.status == 200
    assert archive.headers["Content-Type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(archive.body)) as bundle:
        assert bundle.namelist() == [
            f"{run_id}/page_001.jpg",
            f"{run_id}/page_002.jpg",
        ]


def test_archive_downloads_while_run_is_still_open(api_client):
    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/capture")

    manifest = api_client.get(f"/api/runs/{run_id}")

    assert manifest.json["status"] == "open"
    assert manifest.json["archive_url"] == f"/api/runs/{run_id}/archive"

    archive = api_client.get(f"/api/runs/{run_id}/archive")

    assert archive.status == 200
    with zipfile.ZipFile(io.BytesIO(archive.body)) as bundle:
        assert bundle.namelist() == [f"{run_id}/page_001.jpg"]


class ExplodingCamera:
    """Camera whose captures always fail, for exercising error recording."""

    streaming = True
    stream_output = None

    def capture_file(self, path):
        raise RuntimeError("sensor timeout")


def test_custom_handler_overrides_root_but_inherits_the_api(
    config_manager, config, sample_image
):
    """The seam the demo entry point relies on to serve a page at /."""

    class PageHandler(ExamScanHandler):
        def do_GET(self):
            if self.path == "/":
                self._send_bytes(200, b"<html>demo</html>", "text/html")
                return
            super().do_GET()

    server = ExamScanServer(
        ("127.0.0.1", 0),
        config_manager,
        config,
        FakeCamera(sample_image),
        FakeServoController(),
        FakeStepperMotor(),
        FakeStepperMotor(),
        FakeFan(),
        FakeObstructionMonitor(),
        handler=PageHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ApiClient(server)

        root = client.get("/")
        assert root.status == 200
        assert root.headers["Content-Type"] == "text/html"
        assert root.body == b"<html>demo</html>"

        assert client.get("/api/health").json["ok"] is True
        assert client.post("/api/runs").status == 201
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_list_runs_is_empty_before_any_run(api_client):
    response = api_client.get("/api/runs")

    assert response.status == 200
    assert response.json == {"runs": []}


def test_list_runs_summarises_newest_first(api_client):
    older = api_client.post("/api/runs").json["run_id"]
    newer = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{newer}/capture")

    runs = api_client.get("/api/runs").json["runs"]

    assert [run["run_id"] for run in runs] == [newer, older]
    assert runs[0]["page_count"] == 1
    assert runs[1]["page_count"] == 0
    assert runs[0]["status"] == "open"


def test_delete_all_runs_removes_run_dirs_and_preserves_root(api_server, api_client):
    first = api_client.post("/api/runs").json["run_id"]
    second = api_client.post("/api/runs").json["run_id"]
    root = api_server.run_manager.root

    response = api_client.delete("/api/runs")

    assert response.status == 200
    assert response.json["ok"] is True
    assert response.json["deleted"] == 2
    assert set(response.json["run_ids"]) == {first, second}
    assert api_client.get("/api/runs").json == {"runs": []}
    assert root.exists()
    assert not (root / first).exists()
    assert not (root / second).exists()
    assert api_server.run_manager.active_run_id is None


def test_delete_all_runs_is_rejected_while_busy(api_server, api_client):
    run_id = api_client.post("/api/runs").json["run_id"]
    assert api_server.operation_lock.acquire(blocking=False)
    api_server.operation_name = "capture"
    try:
        response = api_client.delete("/api/runs")
    finally:
        api_server.operation_name = None
        api_server.operation_lock.release()

    assert response.status == 409
    assert response.json["error"] == "hardware is busy with capture"
    assert api_client.get("/api/runs").json["runs"][0]["run_id"] == run_id


def test_delete_all_runs_leaves_non_run_files_and_folders(api_server, api_client):
    run_id = api_client.post("/api/runs").json["run_id"]
    root = api_server.run_manager.root
    note = root / "note.txt"
    folder = root / "not-a-run"
    nested = folder / "readme.txt"
    note.write_text("keep", encoding="utf-8")
    folder.mkdir()
    nested.write_text("keep", encoding="utf-8")

    response = api_client.delete("/api/runs")

    assert response.status == 200
    assert response.json["deleted"] == 1
    assert response.json["run_ids"] == [run_id]
    assert not (root / run_id).exists()
    assert note.read_text(encoding="utf-8") == "keep"
    assert nested.read_text(encoding="utf-8") == "keep"


def test_delete_unknown_path_returns_not_found(api_client):
    response = api_client.delete("/api/runs/not-a-real-delete")

    assert response.status == 404
    assert response.json["error"] == "not found"


def test_get_run_includes_page_count_like_post_does(api_client):
    run_id = api_client.post("/api/runs").json["run_id"]
    captured = api_client.post(f"/api/runs/{run_id}/capture")

    fetched = api_client.get(f"/api/runs/{run_id}")

    assert fetched.json["page_count"] == captured.json["page_count"] == 1
    assert fetched.json["archive_url"] == captured.json["archive_url"]


def test_capture_failure_is_recorded_in_the_manifest(api_server, api_client):
    api_server.camera = ExplodingCamera()
    run_id = api_client.post("/api/runs").json["run_id"]

    failed = api_client.post(f"/api/runs/{run_id}/capture")

    assert failed.status == 500

    errors = api_client.get(f"/api/runs/{run_id}").json["errors"]

    assert len(errors) == 1
    assert errors[0]["operation"] == "capture"
    assert errors[0]["message"] == "sensor timeout"
    assert errors[0]["page_number"] == 1


def test_archive_of_empty_run_is_rejected(api_client):
    run_id = api_client.post("/api/runs").json["run_id"]

    response = api_client.get(f"/api/runs/{run_id}/archive")

    assert response.status == 400
    assert response.json["error"] == "run has no captured pages"


def test_auto_scan_completes_fixed_page_run(api_client, api_server):
    run_id = api_client.post("/api/runs").json["run_id"]

    completed = api_client.post(f"/api/runs/{run_id}/auto-scan", {"pages": 3})

    assert completed.status == 200
    assert completed.json["status"] == "complete"
    assert completed.json["page_count"] == 3
    assert [item["degrees"] for item in api_server.servos.page_drop.angles] == [
        105,
        45,
        105,
        45,
    ]


def test_auto_scan_without_body_uses_configured_default(api_client, api_server):
    api_server.config["workflow"]["default_pages"] = 2
    run_id = api_client.post("/api/runs").json["run_id"]

    completed = api_client.post(f"/api/runs/{run_id}/auto-scan")

    assert completed.status == 200
    assert completed.json["status"] == "complete"
    assert completed.json["page_count"] == 2


def test_page_turn_drives_every_device(api_client, api_server):
    run_id = api_client.post("/api/runs").json["run_id"]

    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 200
    assert response.json == {"ok": True, "run_id": run_id}

    # Small clamp: seat, hold, lift, seat, hold, lift.
    assert [i["degrees"] for i in api_server.servos.page_clamp_small.angles] == [
        88, 85, 0, 88, 85, 0
    ]
    # Big clamp: seat, hold, lift.
    assert [i["degrees"] for i in api_server.servos.page_clamp_big.angles] == [
        105, 102, 0
    ]
    # Arm down then up, never held.
    assert [i["degrees"] for i in api_server.servos.page_drop.angles] == [105, 45]
    assert all(not i["hold"] for i in api_server.servos.page_drop.angles)
    # Motor 1 goes out and straight home. Motor 2 pre-positions, finishes its
    # first leg, continues alone, then returns.
    assert len(api_server.stepper.moves) == 2
    assert len(api_server.stepper2.moves) == 4


def test_page_turn_runs_when_obstruction_detection_is_disabled(
    api_client, api_server
):
    """No monitor means unguarded operation, not a None callback crash."""
    api_server.obstruction = None
    run_id = api_client.post("/api/runs").json["run_id"]

    response = api_client.post(f"/api/runs/{run_id}/page-turn")
    health = api_client.get("/api/health").json

    assert response.status == 200
    assert len(api_server.stepper.moves) == 2
    assert len(api_server.stepper2.moves) == 4
    assert health["hand_detection"]["state"] == "disabled"
    assert health["hand_detection"]["safe_to_move"] is True


def test_page_turn_runs_the_fan_and_always_shuts_it_off(api_client, api_server):
    """The fan spins up for the drop and is back to 0 by the end."""
    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    assert 100 in api_server.fan.duties
    assert api_server.fan.duty_pct == 0


def test_page_turn_shuts_the_fan_off_when_a_phase_fails(api_client, api_server):
    """A fan left at full speed after a failure is the thing to avoid."""

    def boom(*args, **kwargs):
        raise RuntimeError("arm jammed")

    api_server.servos.page_drop.set_angle = boom

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 500
    assert api_server.fan.duty_pct == 0


def test_page_turn_keeps_motor_one_energised_until_it_goes_home(
    api_client, api_server
):
    """Motor 1 holds the page, so it must not de-energise between phases.

    Only the final home move lets go - anything earlier would let the wheel
    slip under load.
    """
    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    held = [move["keep_enabled"] for move in api_server.stepper.moves]
    assert held == [True, False]
    assert api_server.stepper.enabled is False
    # Motor 2 never holds anything.
    assert all(not move["keep_enabled"] for move in api_server.stepper2.moves)


def test_motor_one_returns_exactly_while_motor_two_keeps_its_shortfall(
    api_client, api_server, config
):
    """The early motor 1 return is exact; motor 2 retains its correction."""
    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    m1, m2 = config["motor"], config["motor2"]
    short2 = round(m2["steps_per_rev"] * m2["return_short_degrees"] / 360)

    first, home = api_server.stepper.moves
    assert home["steps"] == first["steps"]
    assert home["clockwise"] is not first["clockwise"]

    m2_preposition, m2_remainder, m2_shared, m2_home = api_server.stepper2.moves
    m2_first = m2_preposition["steps"] + m2_remainder["steps"]
    assert m2_home["steps"] == m2_first + m2_shared["steps"] - short2
    assert m2_home["clockwise"] is not m2_preposition["clockwise"]


def test_page_turn_returns_exactly_when_no_shortfall_is_configured(
    api_client, api_server
):
    """return_short_degrees = 0 restores the exact round trip."""
    api_server.config["motor"]["return_short_degrees"] = 0
    api_server.config["motor2"]["return_short_degrees"] = 0

    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    first, home = api_server.stepper.moves
    assert home["steps"] == first["steps"]

    m2_preposition, m2_remainder, m2_shared, m2_home = api_server.stepper2.moves
    assert m2_home["steps"] == (
        m2_preposition["steps"] + m2_remainder["steps"] + m2_shared["steps"]
    )


@pytest.mark.parametrize("preposition_degrees", [0.0, 45.0, 90.0])
def test_motor_two_preposition_splits_the_first_leg_exactly(
    api_client, api_server, preposition_degrees
):
    """The split changes timing, not total travel or return geometry."""
    motor = api_server.config["motor2"]
    motor["preposition_degrees"] = preposition_degrees

    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    first = round(motor["steps_per_rev"] * motor["page_turn_degrees"] / 360)
    preposition = round(motor["steps_per_rev"] * preposition_degrees / 360)
    remainder = first - preposition
    shared = round(motor["steps_per_rev"] * motor["shared_degrees"] / 360)
    short = round(
        motor["steps_per_rev"] * motor["return_short_degrees"] / 360
    )
    expected = [steps for steps in (preposition, remainder) if steps]
    expected.extend([shared, first + shared - short])

    assert [move["steps"] for move in api_server.stepper2.moves] == expected
    assert sum(expected[: len(expected) - 2]) == first
    assert all(
        move["clockwise"] == motor["default_clockwise"]
        for move in api_server.stepper2.moves[:-1]
    )
    assert api_server.stepper2.moves[-1]["clockwise"] != motor["default_clockwise"]


def test_shared_sequence_remains_available_as_a_config_rollback(
    api_client, api_server
):
    api_server.config["workflow"]["turn_sequence"] = "shared"

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    motor1 = api_server.config["motor"]
    short = round(
        motor1["steps_per_rev"] * motor1["return_short_degrees"] / 360
    )
    first, shared_out, shared_back, home = api_server.stepper.moves
    assert response.status == 200
    assert len(api_server.stepper2.moves) == 4
    assert shared_out["steps"] == shared_back["steps"]
    assert shared_out["clockwise"] is not shared_back["clockwise"]
    assert home["steps"] == first["steps"] - short


@pytest.mark.parametrize("mode", ["motor2_only", "shared"])
def test_preposition_runs_before_arm_lift_while_the_fan_is_on(
    api_client, api_server, mode
):
    events = []
    api_server.config["workflow"]["turn_sequence"] = mode

    original_m1_move = api_server.stepper.move_steps
    original_m2_move = api_server.stepper2.move_steps
    original_arm_move = api_server.servos.page_drop.set_angle
    original_fan_duty = api_server.fan.set_duty

    def m1_move(*args, **kwargs):
        events.append("m1")
        return original_m1_move(*args, **kwargs)

    def m2_move(*args, **kwargs):
        events.append(("m2", api_server.fan.duty_pct))
        return original_m2_move(*args, **kwargs)

    def arm_move(degrees, *args, **kwargs):
        events.append(f"arm:{degrees}")
        return original_arm_move(degrees, *args, **kwargs)

    def fan_duty(percent):
        events.append(f"fan:{percent}")
        return original_fan_duty(percent)

    api_server.stepper.move_steps = m1_move
    api_server.stepper2.move_steps = m2_move
    api_server.servos.page_drop.set_angle = arm_move
    api_server.fan.set_duty = fan_duty

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    first_m1 = events.index("m1")
    preposition = next(
        index for index, event in enumerate(events)
        if isinstance(event, tuple) and event[0] == "m2"
    )
    arm_up = events.index("arm:45")
    fan_off = events.index("fan:0", arm_up)
    motor2 = api_server.config["motor2"]
    preposition_steps = round(
        motor2["steps_per_rev"] * motor2["preposition_degrees"] / 360
    )

    assert response.status == 200
    assert first_m1 < preposition < arm_up < fan_off
    assert events[preposition] == ("m2", 100.0)
    assert len(api_server._phases) == 16
    assert sum(
        move["requested"] == preposition_steps
        and move["clockwise"] == motor2["default_clockwise"]
        for move in api_server.stepper2.moves
    ) == 1


def test_motor_two_only_sequence_does_not_build_a_parallel_move(
    api_client, api_server
):
    def unexpected_parallel(*args, **kwargs):
        raise AssertionError("motor2_only must not use parallel movement")

    api_server._parallel_move = unexpected_parallel
    run_id = api_client.post("/api/runs").json["run_id"]

    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 200


def test_page_turn_order_hands_the_page_between_the_clamps(api_client, api_server):
    """The page is never unclamped: each clamp grips before the other lets go."""
    order = []
    api_server.config["workflow"]["motor_pause"] = 0.25

    def record(label, servo):
        def set_angle(
            degrees, settle_time=None, slow_start=False, hold=False, abort_check=None
        ):
            order.append(f"{label}:{degrees}")
            return True

        servo.set_angle = set_angle

    record("small", api_server.servos.page_clamp_small)
    record("big", api_server.servos.page_clamp_big)
    record("arm", api_server.servos.page_drop)
    def stepper_stub(label):
        def move_steps(
            steps, clockwise=True, step_delay=None, keep_enabled=False, abort_check=None
        ):
            order.append(f"{label}:{'cw' if clockwise else 'ccw'}")
            return steps

        return move_steps

    api_server.stepper.move_steps = stepper_stub("m1")
    api_server.stepper2.move_steps = stepper_stub("m2")

    original_fan_duty = api_server.fan.set_duty

    def fan_duty(percent):
        order.append(f"fan:{percent}")
        return original_fan_duty(percent)

    api_server.fan.set_duty = fan_duty

    def paced(seconds):
        def run(abort):
            if seconds:
                order.append(f"pause:{seconds}")
            return True

        return run

    api_server._paced = paced

    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    preposition = order.index("m2:cw")
    assert order[preposition:preposition + 7] == [
        "m2:cw", "pause:0.25", "arm:45", "fan:0", "m1:ccw",
        "pause:0.25", "small:88"
    ]
    order = [
        event for event in order
        if not event.startswith("pause:") and not event.startswith("fan:")
    ]

    assert order == [
        "small:88", "small:85",      # [1] small clamp grips
        "arm:105",                   # [3] arm down
        "big:105", "big:102",        # [4] big clamp takes over
        "small:0",                   # [5] small clamp releases
        "m1:cw",                     # [6] motor 1 out, still energised
        "m2:cw",                     # [7] motor 2 pre-position
        "arm:45",                    # [8] arm clear
        "m1:ccw",                    # [10] motor 1 returns exactly
        "small:88", "small:85",      # [11] small clamp grips again
        "big:0",                     # [12] big clamp releases
        "m2:cw",                     # [13] motor 2 out remainder
        "m2:cw",                     # [14] motor 2 continues alone
        "m2:ccw",                    # [15] motor 2 home
        "small:0",                   # [16] small clamp off
    ]


def test_page_turn_surfaces_a_failure_from_the_parallel_move(
    api_client, api_server
):
    """An exception inside a worker thread must not be swallowed.

    Threads do not propagate to the joining thread, so without the re-raise a
    dead motor would report a successful page turn on a page that never moved.
    """

    def boom(*args, **kwargs):
        raise RuntimeError("motor 2 stalled")

    api_server.config["workflow"]["turn_sequence"] = "shared"
    api_server.stepper2.move_steps = boom

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 500


def test_concurrent_hardware_actions_return_409(api_server, api_client, sample_image):
    api_server.camera = FakeCamera(sample_image, delay=0.4)
    run_id = api_client.post("/api/runs").json["run_id"]
    first = {}

    def capture():
        first["response"] = api_client.post(f"/api/runs/{run_id}/capture")

    worker = threading.Thread(target=capture)
    worker.start()
    time.sleep(0.1)

    second = api_client.post(f"/api/runs/{run_id}/capture")
    worker.join(timeout=2)

    assert first["response"].status == 200
    assert second.status == 409
    assert second.json["error"].startswith("hardware is busy")


def test_page_turn_is_refused_while_a_hand_is_present(api_client, api_server):
    """The mechanism comes down on the bed, so it must not start on a hand."""
    api_server.obstruction.hand_present = True

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 409
    assert "not clear" in response.json["error"]
    # Nothing moved and the fan never started.
    assert api_server.stepper.moves == []
    assert api_server.servos.page_clamp_small.angles == []
    assert api_server.fan.duty_pct == 0


def test_capture_waits_for_an_idle_hand_to_clear(api_client, api_server):
    """The continuous idle verdict gates capture as well as page motion."""
    api_server.obstruction.hand_present = True
    api_server.obstruction.clear_after_polls = 3

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/capture")

    assert response.status == 200
    assert response.json["page_count"] == 1
    assert api_server.obstruction.waits == 1


def test_capture_times_out_without_writing_while_hand_remains(api_client, api_server):
    api_server.obstruction.hand_present = True

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/capture")

    assert response.status == 409
    assert "not clear" in response.json["error"]
    manifest = api_client.get(f"/api/runs/{run_id}").json
    assert manifest["page_count"] == 0
    assert any(error["operation"] == "capture" for error in manifest["errors"])


def test_page_turn_pauses_and_resumes_when_the_hand_clears(api_client, api_server):
    """A hand stops the turn where it stands; withdrawing it lets it finish."""
    api_server.obstruction.hand_present = True
    api_server.obstruction.clear_after_polls = 3

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 200
    assert len(api_server.stepper.moves) == 2
    assert api_server.obstruction.waits >= 1


def test_a_refused_page_turn_is_recorded_in_the_manifest(api_client, api_server):
    """An unattended auto-scan needs the reason it stopped written down."""
    api_server.obstruction.hand_present = True

    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    manifest = api_client.get(f"/api/runs/{run_id}").json
    assert any(e["operation"] == "page-turn" for e in manifest["errors"])


def test_the_gate_is_polled_throughout_the_turn(api_client, api_server):
    """Not just at the start - a hand can arrive at any point in the sequence.

    Every move and every settle checks, so the count runs far past the sixteen
    phase boundaries a start-only gate would have managed.
    """
    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    assert api_server.obstruction.polls > 16


def turn_totals(server):
    """Net steps each motor was actually pulsed, by direction."""
    def net(moves):
        return sum(m["steps"] if m["clockwise"] else -m["steps"] for m in moves)

    return net(server.stepper.moves), net(server.stepper2.moves)


def test_an_interrupted_turn_moves_exactly_as_far_as_an_uninterrupted_one(
    api_client, api_server
):
    """The whole reason resuming continues the remainder instead of restarting.

    Re-running an interrupted move would add the steps already taken on top,
    creeping both wheels round a little more on every interrupted page - and
    nothing measures wheel position, so it would never surface.
    """
    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")
    clean = turn_totals(api_server)

    api_server.stepper.moves.clear()
    api_server.stepper2.moves.clear()
    # Land the hand inside a stepper run, not between phases - a move cut off
    # partway is the only case where restarting rather than resuming would show.
    api_server.obstruction.polls = 0
    api_server.obstruction.obstruct_after_polls = 40
    api_server.obstruction.clear_after_polls = 3

    api_client.post(f"/api/runs/{run_id}/page-turn")

    partial = [
        m for m in api_server.stepper.moves + api_server.stepper2.moves
        if m["steps"] != m["requested"]
    ]
    assert partial, "expected a move to be cut off mid-run"
    assert turn_totals(api_server) == clean


@pytest.mark.parametrize("target_move", [1, 2, 3])
def test_each_motor_two_outward_move_resumes_without_duplicate_steps(
    api_client, api_server, target_move
):
    """A hand can interrupt either split half without replaying completed steps."""
    run_id = api_client.post("/api/runs").json["run_id"]
    original_move = api_server.stepper2.move_steps
    call_count = 0

    def interrupt_selected_move(
        steps, clockwise=True, step_delay=None, keep_enabled=False, abort_check=None
    ):
        nonlocal call_count
        call_count += 1
        selected = call_count == target_move
        checks = 0

        def trigger_hand():
            nonlocal checks
            checks += 1
            if selected and checks == 3:
                api_server.obstruction.hand_present = True
                api_server.obstruction.clear_after_polls = (
                    api_server.obstruction.polls + 3
                )
            return abort_check()

        return original_move(
            steps,
            clockwise=clockwise,
            step_delay=step_delay,
            keep_enabled=keep_enabled,
            abort_check=trigger_hand,
        )

    api_server.stepper2.move_steps = interrupt_selected_move
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    motor = api_server.config["motor2"]
    first = round(motor["steps_per_rev"] * motor["page_turn_degrees"] / 360)
    shared = round(motor["steps_per_rev"] * motor["shared_degrees"] / 360)
    short = round(
        motor["steps_per_rev"] * motor["return_short_degrees"] / 360
    )
    expected_net = (
        first + shared - (first + shared - short)
        if motor["default_clockwise"]
        else -(first + shared) + (first + shared - short)
    )

    assert response.status == 200
    assert any(
        move["steps"] != move["requested"] for move in api_server.stepper2.moves
    )
    assert turn_totals(api_server)[1] == expected_net


def test_motor_one_early_return_resumes_without_duplicate_steps(
    api_client, api_server
):
    run_id = api_client.post("/api/runs").json["run_id"]
    original_move = api_server.stepper.move_steps
    call_count = 0

    def interrupt_return(
        steps, clockwise=True, step_delay=None, keep_enabled=False, abort_check=None
    ):
        nonlocal call_count
        call_count += 1
        returning = call_count == 2
        checks = 0

        def trigger_hand():
            nonlocal checks
            checks += 1
            if returning and checks == 3:
                api_server.obstruction.hand_present = True
                api_server.obstruction.clear_after_polls = (
                    api_server.obstruction.polls + 3
                )
            return abort_check()

        return original_move(
            steps,
            clockwise=clockwise,
            step_delay=step_delay,
            keep_enabled=keep_enabled,
            abort_check=trigger_hand,
        )

    api_server.stepper.move_steps = interrupt_return
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 200
    assert any(
        move["steps"] != move["requested"] for move in api_server.stepper.moves
    )
    assert turn_totals(api_server)[0] == 0


def test_a_turn_that_never_clears_stops_and_reports_where(api_client, api_server):
    """The operator needs to know what state the mechanism was left in."""
    api_server.obstruction.hand_present = True

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 409
    assert "stopped at phase" in response.json["error"]
    # Safe state: fan off and nothing left driving.
    assert api_server.fan.duty_pct == 0
    assert api_server.stepper.enabled is False
    assert api_server.stepper2.enabled is False


def test_the_fan_is_off_while_paused_and_back_on_when_resumed(api_client, api_server):
    """Spinning blades are the actual hazard, so the fan stops for a pause."""
    api_server.obstruction.hand_present = True
    api_server.obstruction.clear_after_polls = 40

    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    # It ran, stopped, and ran again somewhere in the middle.
    assert 100 in api_server.fan.duties
    assert api_server.fan.duties.count(0) >= 2
    assert api_server.fan.duty_pct == 0


def test_health_reports_a_hand_without_a_run(api_client, api_server):
    api_server.obstruction.hand_present = True

    health = api_client.get("/api/health").json

    assert health["hand_present"] is True
    assert health["hand_detection"] == {
        "mode": "fake",
        "state": "confirmed",
        "hand_present": True,
        "safe_to_move": False,
        "reason": "confirmed hand is in the scan area",
        "clear_count": 0,
        "clear_frames": 1,
        "palm_score": None,
        "presence_score": 1.0,
        "confirmed_hands": 1,
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
    assert health["paused"] is False
    assert health["paused_phase"] is None


def test_holds_are_kept_alive_while_paused(api_client, api_server, config):
    """A pause must not let the clamps quietly time out and drop the page.

    max_hold_seconds detaches a held servo on a timer rather than raising, so
    without re-asserting, a long pause would end with the grip already gone and
    nothing having said so.
    """
    for name in ("page_clamp_small", "page_clamp_big"):
        api_server.config["servos"][name]["max_hold_seconds"] = 1.0
    api_server.obstruction.wait_timeout_seconds = 5.0
    # Land the pause after the small clamp is holding, and sit there a while.
    api_server.obstruction.obstruct_after_polls = 3
    api_server.obstruction.clear_after_polls = 120

    run_id = api_client.post("/api/runs").json["run_id"]
    response = api_client.post(f"/api/runs/{run_id}/page-turn")

    assert response.status == 200
    holds = [a for a in api_server.servos.page_clamp_small.angles if a["hold"]]
    # Two in the sequence itself; anything beyond that is the pause keeping it.
    assert len(holds) > 2
