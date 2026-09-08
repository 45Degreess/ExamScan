import http.client
import json
import threading
from copy import deepcopy

import pytest
import tomli_w
from PIL import Image

from config import DEFAULT_CONFIG, ConfigManager
from fakes import (
    FakeCamera,
    FakeServo,
    FakeServoController,
    FakeStepperMotor,
    FakeWheelMotor,
)
from server import ExamScanServer

# Re-exported so tests can import the fakes from here rather than reaching
# into the module the dev server also uses.
__all__ = [
    "FakeCamera",
    "FakeServo",
    "FakeServoController",
    "FakeStepperMotor",
    "FakeWheelMotor",
]


@pytest.fixture()
def sample_image(tmp_path):
    path = tmp_path / "sample.jpg"
    Image.new("RGB", (320, 200), color=(235, 238, 242)).save(path, format="JPEG")
    return path


@pytest.fixture()
def config_dict(tmp_path):
    """A full valid config with paths redirected into tmp_path.

    Tests that need TOML bytes dump this, so nothing has to string-patch a
    hand-written config literal.
    """
    config = deepcopy(DEFAULT_CONFIG)
    config["paths"]["runs_dir"] = str(tmp_path / "runs")
    # page_turn() sleeps these for real, and they exist to pace a mechanism no
    # test is driving. Left at their defaults, a multi-page auto-scan outruns the
    # client timeout.
    for pause in ("servo_down_pause", "wheel_pause", "stepper_pause", "servo_up_pause"):
        config["workflow"][pause] = 0.0
    return config


@pytest.fixture()
def config_text(config_dict):
    return tomli_w.dumps(config_dict)


@pytest.fixture()
def config_manager(tmp_path, config_text):
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")
    return ConfigManager(config_path)


@pytest.fixture()
def config(config_manager):
    return config_manager.load()


class Response:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def json(self):
        return json.loads(self.body.decode("utf-8"))


class ApiClient:
    def __init__(self, server):
        self.port = server.server_address[1]

    def request(self, method, path, body=None, content_type="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            headers["Content-Type"] = content_type
        conn.request(method, path, body=data, headers=headers)
        raw = conn.getresponse()
        response = Response(raw.status, dict(raw.getheaders()), raw.read())
        conn.close()
        return response

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body)

    def put(self, path, body=None):
        return self.request("PUT", path, body)


@pytest.fixture()
def api_server(config_manager, config, sample_image):
    server = ExamScanServer(
        ("127.0.0.1", 0),
        config_manager,
        config,
        FakeCamera(sample_image),
        FakeWheelMotor(),
        FakeServoController(),
        FakeStepperMotor(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture()
def api_client(api_server):
    return ApiClient(api_server)
