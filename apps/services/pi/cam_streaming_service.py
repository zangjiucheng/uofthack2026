"""
Minimal Pi camera MJPEG streaming using picamera2.
"""

import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.services import Service
import cv2

try:
    from picamera2 import Picamera2
except Exception:  # pragma: no cover - optional dependency
    Picamera2 = None

HTML = """
<!DOCTYPE html>
<html>
<head><title>Live Stream</title></head>
<body style="margin:0;background:black;display:flex;align-items:center;justify-content:center;">
<img src="stream.mjpg" style="width:100vw;height:100vh;object-fit:contain;" />
</body>
</html>
"""


def run_cam_streaming_service(video_port: int = 9000, use_local_cam: bool = False):
    if use_local_cam:
        cap = cv2.VideoCapture(0)

        class Capture:
            def read(self):
                ok, frame = cap.read()
                if not ok:
                    return False, None
                ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                return ok, jpg.tobytes() if ok else None

            def release(self):
                cap.release()

        capture = Capture()
    else:
        if Picamera2 is None:
            raise RuntimeError("picamera2 not available; cannot stream Pi camera")

        picam2 = Picamera2()
        config = picam2.create_video_configuration(
            main={"size": (640, 480), "format": "YUV420"},
            controls={"FrameDurationLimits": (11111, 11111), "NoiseReductionMode": 1},
        )
        picam2.configure(config)
        picam2.start()

        class Capture:
            def read(self):
                frame = picam2.capture_array()
                frame = cv2.cvtColor(frame, cv2.COLOR_YUV420p2BGR)
                ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                return ok, jpg.tobytes() if ok else None

            def release(self):
                picam2.stop()

        capture = Capture()

    class MJPEGHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/stream.mjpg"):
                self.send_response(404)
                self.end_headers()
                return
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(HTML.encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    ok, jpg = capture.read()
                    if not ok or jpg is None:
                        time.sleep(0.01)
                        continue
                    self.wfile.write(b"--FRAME\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
            except Exception:
                return

        def log_message(self, *args):
            pass

    print(f"Video: http://0.0.0.0:{video_port}/stream.mjpg")
    HTTPServer(("0.0.0.0", video_port), MJPEGHandler).serve_forever()


class CamStreamingService(Service):
    name = "pi_cam_stream"

    def __init__(self, video_port: int = 9000):
        self.video_port = video_port
        self._thread: threading.Thread | None = None
        self._use_local_cam = os.environ.get("PI_DEBUG_LOCAL", "0") == "1"
        self._enabled = os.environ.get("PI_DEBUG_LOCAL", "0") == "1"

    def start(self):
        if not self._enabled:
            print("[pi_robot] Camera streaming disabled (PI_DEBUG_LOCAL!=1)")
            return
        print(f"[pi_robot] Streaming camera at port {self.video_port} (local cam: {self._use_local_cam})")
        if self._thread and self._thread.is_alive():
            return

        def runner():
            run_cam_streaming_service(video_port=self.video_port, use_local_cam=self._use_local_cam)

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

    def stop(self):
        # MJPEG server runs forever; best-effort join to avoid leaked threads on shutdown.
        if self._thread:
            self._thread.join(timeout=1.0)


def start_cam_streaming_background(video_port: int = 9000) -> threading.Thread:
    svc = CamStreamingService(video_port=video_port)
    svc.start()
    return svc._thread if svc._thread else None


if __name__ == "__main__":
    run_cam_streaming_service()
