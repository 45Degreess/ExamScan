import io
import threading
import time
import zipfile

import tomli_w

from server import ExamScanHandler, ExamScanServer
from tests.conftest import (
    ApiClient,
    FakeCamera,
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

    # Clamp down then up, arm down then up.
    assert [i["degrees"] for i in api_server.servos.page_clamp_big.angles] == [105, 0]
    assert [i["degrees"] for i in api_server.servos.page_drop.angles] == [105, 45]


def test_page_turn_splits_the_outward_run_and_returns_exactly(api_client, api_server):
    """The two outward halves must sum to the single return move.

    Splitting in steps rather than degrees is what guarantees this - halving the
    degrees and rounding twice can land a step off, leaving the wheel short of
    where it started on every page.
    """
    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    first, second, back = api_server.stepper.moves

    assert first["steps"] + second["steps"] == back["steps"]
    assert first["clockwise"] is second["clockwise"]
    assert back["clockwise"] is not first["clockwise"]


def test_page_turn_order_lifts_the_clamp_mid_run(api_client, api_server):
    """Clamp drops before the arm and lifts between the two stepper halves."""
    order = []
    api_server.servos.page_clamp_big.set_angle = lambda degrees, settle_time=None: (
        order.append(f"clamp:{degrees}")
    )
    api_server.servos.page_drop.set_angle = lambda degrees, settle_time=None: (
        order.append(f"arm:{degrees}")
    )
    api_server.stepper.move_steps = lambda steps, clockwise=True: order.append(
        f"stepper:{'cw' if clockwise else 'ccw'}"
    )

    run_id = api_client.post("/api/runs").json["run_id"]
    api_client.post(f"/api/runs/{run_id}/page-turn")

    assert order == [
        "clamp:105",
        "arm:105",
        "stepper:cw",
        "clamp:0",
        "stepper:cw",
        "arm:45",
        "stepper:ccw",
    ]


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
