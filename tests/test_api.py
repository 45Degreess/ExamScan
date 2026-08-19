import io
import threading
import time
import zipfile

import tomli_w

from server import ExamScanHandler, ExamScanServer
from tests.conftest import (
    ApiClient,
    FakeCamera,
    FakeFan,
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
    # Motor 1 out, shared, shared back, home. Motor 2 out, shared, home.
    assert len(api_server.stepper.moves) == 4
    assert len(api_server.stepper2.moves) == 3


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
    assert held == [True, True, True, False]
    assert api_server.stepper.enabled is False
    # Motor 2 never holds anything.
    assert all(not move["keep_enabled"] for move in api_server.stepper2.moves)


def test_page_turn_stops_short_of_home_by_the_configured_degrees(
    api_client, api_server, config
):
    """Each motor's final return deliberately undershoots.

    Splitting in steps rather than degrees is what keeps the arithmetic exact;
    return_short_degrees is then subtracted from the last move only.
    """
    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    m1, m2 = config["motor"], config["motor2"]
    short1 = round(m1["steps_per_rev"] * m1["return_short_degrees"] / 360)
    short2 = round(m2["steps_per_rev"] * m2["return_short_degrees"] / 360)

    first, shared_out, shared_back, home = api_server.stepper.moves
    assert home["steps"] == first["steps"] - short1
    assert shared_out["steps"] == shared_back["steps"]
    assert shared_back["clockwise"] is not shared_out["clockwise"]

    m2_first, m2_shared, m2_home = api_server.stepper2.moves
    assert m2_home["steps"] == m2_first["steps"] + m2_shared["steps"] - short2
    assert m2_home["clockwise"] is not m2_first["clockwise"]


def test_page_turn_returns_exactly_when_no_shortfall_is_configured(
    api_client, api_server
):
    """return_short_degrees = 0 restores the exact round trip."""
    api_server.config["motor"]["return_short_degrees"] = 0
    api_server.config["motor2"]["return_short_degrees"] = 0

    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    first, shared_out, shared_back, home = api_server.stepper.moves
    assert home["steps"] == first["steps"]

    m2_first, m2_shared, m2_home = api_server.stepper2.moves
    assert m2_home["steps"] == m2_first["steps"] + m2_shared["steps"]


def test_page_turn_order_hands_the_page_between_the_clamps(api_client, api_server):
    """The page is never unclamped: each clamp grips before the other lets go."""
    order = []

    def record(label, servo):
        def set_angle(degrees, settle_time=None, slow_start=False, hold=False):
            order.append(f"{label}:{degrees}")

        servo.set_angle = set_angle

    record("small", api_server.servos.page_clamp_small)
    record("big", api_server.servos.page_clamp_big)
    record("arm", api_server.servos.page_drop)
    api_server.stepper.move_steps = (
        lambda steps, clockwise=True, step_delay=None, keep_enabled=False: order.append(
            f"m1:{'cw' if clockwise else 'ccw'}"
        )
    )
    api_server.stepper2.move_steps = (
        lambda steps, clockwise=True, step_delay=None, keep_enabled=False: order.append(
            f"m2:{'cw' if clockwise else 'ccw'}"
        )
    )

    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    # Phase 12 drives both motors on their own threads, so the two entries can
    # land either way round. Sorted in place rather than asserted in a fixed
    # order, or this test would fail on scheduling luck alone.
    order[12:14] = sorted(order[12:14])

    assert order == [
        "small:88", "small:85",      # [1] small clamp grips
        "arm:105",                   # [3] arm down
        "big:105", "big:102",        # [4] big clamp takes over
        "small:0",                   # [5] small clamp releases
        "m1:cw",                     # [6] motor 1 out, still energised
        "arm:45",                    # [7] arm clear
        "small:88", "small:85",      # [9] small clamp grips again
        "big:0",                     # [10] big clamp releases
        "m2:cw",                     # [11] motor 2 out
        "m1:cw", "m2:cw",            # [12] both together, either order
        "m2:ccw",                    # [13] motor 2 home
        "m1:ccw",                    # [14] motor 1 unwinds the shared leg
        "small:0",                   # [15] small clamp off
        "m1:ccw",                    # [16] motor 1 home
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
