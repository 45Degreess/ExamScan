"""ExamScan entry point: real hardware, with a demo web page.

Identical to main.py — same real camera, motor and servos, same API — except
that GET / serves demo.html instead of the JSON service descriptor.

This exists to demonstrate the scanner without the external GUI. It is not the
product interface; the real GUI is a separate remote client that talks to this
same API.

    uv run examscan-demo
"""

from pathlib import Path
from urllib.parse import urlparse

from hardware.factory import build_hardware
from server import ExamScanHandler, load_config, serve

DEMO_PAGE = Path(__file__).parent / "demo.html"
BANNER = "ExamScan DEMO MODE - real hardware, web page served at /"


class DemoHandler(ExamScanHandler):
    """Serves the demo page at /, and everything else exactly as production does.

    The page is read per request so it can be edited and reloaded mid-demo. The
    path is fixed relative to this file rather than coming from config or the
    request, so no static-directory handling or traversal guard is involved.
    """

    def do_GET(self):
        if urlparse(self.path).path == "/":
            try:
                self._send_bytes(200, DEMO_PAGE.read_bytes(), "text/html")
            except OSError:
                self._send_error(404, "demo page not found")
            return
        super().do_GET()


def main():
    config_manager, config = load_config()
    camera, wheel_motor, servos, stepper = build_hardware(config)

    camera.start_recording()

    serve(
        config_manager,
        config,
        camera,
        wheel_motor,
        servos,
        stepper,
        banner=BANNER,
        handler=DemoHandler,
    )


if __name__ == "__main__":
    main()
