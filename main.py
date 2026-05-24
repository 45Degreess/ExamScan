import subprocess
import threading
import time

from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

from hardware.camera import CAPTURE_DIR, CameraServer, make_camera
from hardware.motor import StepperMotor


def get_local_ip():
    result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
    for ip in result.stdout.strip().split():
        if not ip.startswith("127"):
            return ip
    return "localhost"

PORT = 8000


def main():
    CAPTURE_DIR.mkdir(exist_ok=True)

    motor = StepperMotor()
    picam2, camera_config, capture_config = make_camera()
    server = CameraServer(("0.0.0.0", PORT), picam2, camera_config, capture_config, motor)

    picam2.configure(camera_config)
    picam2.start_recording(MJPEGEncoder(), FileOutput(server.stream_output))
    time.sleep(3)

    threading.Thread(target=server.serve_forever, daemon=True).start()

    ip = get_local_ip()
    print(f"Open in browser: http://{ip}:{PORT}")
    print("Running... press Ctrl+C to quit")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.streaming = False
        try:
            picam2.stop_recording()
        except Exception:
            pass
        motor.cleanup()
        print("Stopped.")


if __name__ == "__main__":
    main()
