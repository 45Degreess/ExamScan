"""ExamScan entry point: real hardware, with the engineering Rig UI.

Identical to main.py — same real camera, motor and servos, same API — except
that GET / serves rig.html instead of the JSON service descriptor.

This is a bench-testing interface, not the product operator interface. Its
controls can move physical components.

    uv run examscan-rig
"""

from pathlib import Path
from urllib.parse import urlparse

from .drivers.factory import build_hardware
from .server import ExamScanHandler, load_config, serve

SERVICE_ROOT = Path(__file__).resolve().parents[2]
RIG_PAGE = SERVICE_ROOT / "static" / "rig.html"
BANNER = "ExamScan RIG MODE - real hardware test interface at /"


class RigHandler(ExamScanHandler):
    """Serve the Rig UI at / and inherit all production API behaviour.

    The page is read per request so it can be edited and reloaded during tests. The
    path is fixed relative to this file rather than coming from config or the
    request, so no static-directory handling or traversal guard is involved.
    """

    def do_GET(self):
        if urlparse(self.path).path == "/":
            try:
                self._send_bytes(200, RIG_PAGE.read_bytes(), "text/html")
            except OSError:
                self._send_error(404, "Rig UI page not found")
            return
        super().do_GET()


def main():
    config_manager, config = load_config()
    camera, servos, stepper, stepper2, fan, obstruction = build_hardware(config)

    camera.start_recording()

    serve(
        config_manager,
        config,
        camera,
        servos,
        stepper,
        stepper2,
        fan,
        obstruction,
        banner=BANNER,
        handler=RigHandler,
    )


if __name__ == "__main__":
    main()
