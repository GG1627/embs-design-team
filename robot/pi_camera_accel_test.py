import argparse
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


LOGGER = logging.getLogger("robot.pi_camera_accel_test")


class FrameSource:
    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.backend = "none"
        self._picam: Any = None
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        try:
            from picamera2 import Picamera2  # type: ignore

            self._picam = Picamera2()
            config = self._picam.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"},
                controls={"FrameRate": self.fps},
            )
            self._picam.configure(config)
            self._picam.start()
            time.sleep(0.2)
            self.backend = "picamera2"
            LOGGER.info("Camera backend: picamera2 (%sx%s @ %sfps)", self.width, self.height, self.fps)
            return
        except Exception as exc:
            LOGGER.warning("Picamera2 not available: %s", exc)
            self._picam = None

        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            raise RuntimeError("Failed to open camera with Picamera2 and OpenCV fallback.")
        self.backend = "opencv"
        LOGGER.info("Camera backend: opencv (/dev/video0 fallback)")

    def read_rgb(self) -> np.ndarray | None:
        if self.backend == "picamera2" and self._picam is not None:
            frame = self._picam.capture_array()
            return frame if frame is not None else None

        if self._cap is not None:
            ok, frame = self._cap.read()
            if not ok:
                return None
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        return None

    def close(self) -> None:
        if self._picam is not None:
            try:
                self._picam.stop()
            except Exception:
                pass
            self._picam = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        LOGGER.info("Camera closed.")


def setup_logging() -> Path:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "pi_camera_accel_test.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    LOGGER.info("Logging to %s", log_path)
    return log_path


def check_hailo() -> tuple[bool, str]:
    import_ok = False
    runtime_msg = "hailo_runtime_not_detected"
    try:
        import hailo_platform  # type: ignore  # noqa: F401

        import_ok = True
        runtime_msg = "hailo_runtime_detected"
        LOGGER.info("Hailo runtime import: OK")
    except Exception as exc:
        LOGGER.warning("Hailo runtime import failed: %s", exc)

    cli_path = shutil.which("hailortcli")
    if not cli_path:
        LOGGER.warning("hailortcli not found in PATH.")
        return import_ok, runtime_msg

    try:
        result = subprocess.run(
            [cli_path, "scan"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            LOGGER.info("hailortcli scan succeeded.")
            LOGGER.info("hailortcli output: %s", output.strip() or "<empty>")
            if "device" in output.lower() or "hailo" in output.lower():
                return True, "hailo_runtime_detected_device_visible"
        else:
            LOGGER.warning("hailortcli scan failed (code=%s): %s", result.returncode, output.strip())
    except Exception as exc:
        LOGGER.warning("hailortcli scan exception: %s", exc)

    return import_ok, runtime_msg


def run_camera_test(duration_sec: float) -> tuple[bool, str, int, float]:
    source = FrameSource()
    frames = 0
    backend = "none"
    started = time.time()
    last_log = started

    try:
        source.open()
        backend = source.backend
        end_time = started + duration_sec
        while time.time() < end_time:
            frame = source.read_rgb()
            if frame is not None:
                frames += 1
            now = time.time()
            if now - last_log >= 1.0:
                LOGGER.info("Camera test running: frames=%s elapsed=%.1fs", frames, now - started)
                last_log = now
            time.sleep(0.01)
    finally:
        source.close()

    elapsed = max(0.001, time.time() - started)
    fps = frames / elapsed
    ok = frames > 0
    return ok, backend, frames, fps


def main() -> int:
    parser = argparse.ArgumentParser(description="Raspberry Pi camera + Hailo quick smoke test.")
    parser.add_argument("--duration", type=float, default=4.0, help="Camera test duration in seconds.")
    args = parser.parse_args()

    log_path = setup_logging()
    LOGGER.info("Starting quick test (duration=%.1fs)", args.duration)

    accel_ok, accel_status = check_hailo()
    cam_ok = False
    camera_backend = "none"
    frames = 0
    fps = 0.0

    try:
        cam_ok, camera_backend, frames, fps = run_camera_test(args.duration)
    except Exception as exc:
        LOGGER.exception("Camera test crashed: %s", exc)

    LOGGER.info("Summary: camera_ok=%s backend=%s frames=%s fps=%.1f", cam_ok, camera_backend, frames, fps)
    LOGGER.info("Summary: accelerator_ok=%s status=%s", accel_ok, accel_status)
    LOGGER.info("Log file: %s", log_path)

    if cam_ok and accel_ok:
        LOGGER.info("PASS: camera and accelerator checks look good.")
        return 0

    LOGGER.error("FAIL: check log for camera/accelerator details.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
