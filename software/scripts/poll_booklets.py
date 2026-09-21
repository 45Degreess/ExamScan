"""
Poll GET /sessions/{code}/booklets until no booklet is still 'processing'
(or a timeout), printing each one's run_id/status/mark as it changes. Used
by `make collect-runs` (see ../Makefile) to show collected Pi runs finishing.

Usage: poll_booklets.py <base_url> <cookie_jar> <session_code> [max_seconds]
"""
import json
import subprocess
import sys
import time


def fetch(base_url: str, cookie_jar: str, session_code: str) -> list[dict]:
    out = subprocess.run(
        ["curl", "-s", "-b", cookie_jar, f"{base_url}/sessions/{session_code}/booklets"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)["booklets"]


def main():
    base_url, cookie_jar, session_code = sys.argv[1:4]
    max_seconds = int(sys.argv[4]) if len(sys.argv) > 4 else 180

    deadline = time.time() + max_seconds
    last_status: dict[str, str] = {}
    while True:
        booklets = fetch(base_url, cookie_jar, session_code)
        pending = 0
        for b in booklets:
            key = b.get("run_id") or f"#{b['id']}"
            status = b["status"]
            if last_status.get(key) != status:
                mark = f" mark={b['mark']}" if b.get("mark") is not None else ""
                print(f"  {key}: {status}{mark}")
                last_status[key] = status
            if status == "processing":
                pending += 1

        if pending == 0:
            print("All runs finished processing.")
            return
        if time.time() > deadline:
            print(f"Timed out after {max_seconds}s with {pending} run(s) still processing.")
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
