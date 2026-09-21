"""
Minimal stand-in for the Raspberry Pi's hardware API, used by `make
collect-runs` (see ../Makefile) to test the real /collect-runs pipeline
without physical hardware. Serves a folder of pre-made run .zip archives as
if each one were a completed Pi run:

  GET /api/runs                   -> {"runs": [{"run_id": <zip stem>, "status": "complete"}, ...]}
  GET /api/runs/<run_id>/archive  -> raw bytes of <run_id>.zip

Each zip's run_id is its filename without the .zip extension. Internal
layout follows the real Pi archive convention that _process_collected_run
(software/routes.py) already handles: either images directly at the top
level, or nested one level under a single folder.

Usage: python3 fake_pi_server.py <folder-of-zips> [port]
"""
import http.server
import json
import sys
from pathlib import Path


def make_handler(runs_dir: Path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print(f"[fake-pi] {self.address_string()} {fmt % args}")

        def do_GET(self):
            if self.path == "/api/runs":
                runs = [
                    {"run_id": p.stem, "status": "complete"}
                    for p in sorted(runs_dir.glob("*.zip"))
                ]
                self._send_json({"runs": runs})
                return

            if self.path.startswith("/api/runs/") and self.path.endswith("/archive"):
                run_id = self.path[len("/api/runs/"):-len("/archive")]
                zip_path = runs_dir / f"{run_id}.zip"
                if not zip_path.is_file():
                    self.send_error(404, f"No such run: {run_id}")
                    return
                data = zip_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            self.send_error(404)

        def _send_json(self, payload: dict):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    if len(sys.argv) < 2:
        print("Usage: fake_pi_server.py <folder-of-zips> [port]", file=sys.stderr)
        sys.exit(1)

    runs_dir = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9100
    if not runs_dir.is_dir():
        print(f"Not a directory: {runs_dir}", file=sys.stderr)
        sys.exit(1)

    zips = sorted(runs_dir.glob("*.zip"))
    if not zips:
        print(f"Warning: no .zip files found directly in {runs_dir}", file=sys.stderr)

    print(f"[fake-pi] Serving {len(zips)} run(s) from {runs_dir} on http://127.0.0.1:{port}")
    for z in zips:
        print(f"[fake-pi]   run_id={z.stem}")

    server = http.server.HTTPServer(("127.0.0.1", port), make_handler(runs_dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
