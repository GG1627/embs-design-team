import os
import logging
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import joblib
# Reduce non-critical native logs before importing MediaPipe/TFLite.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("GLOG_minloglevel", "2")
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

LOGGER = logging.getLogger("robot.pi_health_monitor")


class FrameSource:
    """OpenCV camera source for libcamerify-based Pi camera access."""

    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.backend = "opencv"
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            raise RuntimeError(
                "Could not open /dev/video0 with OpenCV. "
                "Run app with libcamerify: libcamerify python robot/pi_main.py"
            )
        LOGGER.info("Camera backend selected: opencv (/dev/video0 via libcamerify recommended)")

    def read_rgb(self) -> np.ndarray | None:
        if self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                return None
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        return None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        LOGGER.info("Camera backend closed.")


@dataclass
class HealthSnapshot:
    timestamp: float
    monitoring_ready: bool
    posture_ready: bool
    eye_ready: bool
    posture_prediction: str
    bad_posture_ratio_60s: float
    bad_posture_seconds_60s: float
    blink_count_60s: int
    long_closure_count_60s: int
    max_closure_seconds_60s: float
    latest_eye_closure_seconds: float
    status: str
    camera_backend: str = "unknown"
    accelerator_status: str = "cpu_only"
    error: str | None = None


class HealthMonitor:
    CALIBRATION_SECONDS = 10.0
    HISTORY_WINDOW_SECONDS = 60.0
    LONG_CLOSURE_SECONDS = 1.2
    EYE_CLOSED_THRESHOLD = 0.75
    POSTURE_SAMPLE_SECONDS = 1.0
    FACE_LOST_RESET_SECONDS = 0.6

    LEFT_EYE = [33, 160, 158, 133, 153, 144]
    RIGHT_EYE = [362, 385, 387, 263, 373, 380]

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.mia_dir = project_root / "mia"
        self.pose_model_path = self.mia_dir / "posture_model.pkl"
        self.pose_task_path = self.mia_dir / "pose_landmarker_lite.task"
        self.face_task_path = self.mia_dir / "face_landmarker.task"

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self._state = HealthSnapshot(
            timestamp=time.time(),
            monitoring_ready=False,
            posture_ready=False,
            eye_ready=False,
            posture_prediction="calibrating",
            bad_posture_ratio_60s=0.0,
            bad_posture_seconds_60s=0.0,
            blink_count_60s=0,
            long_closure_count_60s=0,
            max_closure_seconds_60s=0.0,
            latest_eye_closure_seconds=0.0,
            status="starting",
            camera_backend="unknown",
            accelerator_status="cpu_only",
            error=None,
        )

    @staticmethod
    def _accelerator_status() -> str:
        LOGGER.info("Accelerator mode: cpu_only (Hailo checks disabled).")
        return "cpu_only"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        LOGGER.info("HealthMonitor worker thread started.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        LOGGER.info("HealthMonitor worker thread stopped.")

    def get_snapshot(self) -> HealthSnapshot:
        with self._lock:
            return HealthSnapshot(**self._state.__dict__)

    def _set_state(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self._state, key, value)
            self._state.timestamp = time.time()

    @staticmethod
    def _compute_ear(eye: np.ndarray) -> float:
        a = np.linalg.norm(eye[1] - eye[5])
        b = np.linalg.norm(eye[2] - eye[4])
        c = np.linalg.norm(eye[0] - eye[3])
        if c == 0:
            return 0.0
        return float((a + b) / (2.0 * c))

    def _run(self) -> None:
        frame_source: FrameSource | None = None
        try:
            if not self.pose_model_path.exists():
                raise RuntimeError(f"Missing model file: {self.pose_model_path}")
            if not self.pose_task_path.exists():
                raise RuntimeError(f"Missing MediaPipe task file: {self.pose_task_path}")
            if not self.face_task_path.exists():
                raise RuntimeError(f"Missing MediaPipe task file: {self.face_task_path}")

            posture_model = joblib.load(self.pose_model_path)
            LOGGER.info("Loaded posture model: %s", self.pose_model_path)
            frame_source = FrameSource(width=1280, height=720, fps=30)
            frame_source.open()
            accelerator_status = self._accelerator_status()
            self._set_state(
                camera_backend=frame_source.backend,
                accelerator_status=accelerator_status,
                status="camera_ready",
            )

            pose_options = mp_vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(self.pose_task_path)),
                running_mode=mp_vision.RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            face_options = mp_vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(self.face_task_path)),
                running_mode=mp_vision.RunningMode.VIDEO,
                num_faces=1,
            )

            posture_samples: deque[tuple[float, bool]] = deque()
            blink_events: deque[tuple[float, float]] = deque()

            posture_calibration_start = time.time()
            eye_calibration_start = time.time()

            tilt_samples: list[float] = []
            shoulder_samples: list[float] = []
            ratio_samples: list[float] = []

            ear_samples: list[float] = []

            posture_ready = False
            eye_ready = False
            posture_prediction = "calibrating"

            baseline_tilt = 0.0
            baseline_shoulder = 0.0
            baseline_ratio = 0.0
            baseline_ear = 0.0

            eye_closed = False
            closure_start = 0.0
            last_posture_sample_time = 0.0
            last_face_seen_time = 0.0

            start_ts = time.monotonic()

            with (
                mp_vision.PoseLandmarker.create_from_options(pose_options) as pose_detector,
                mp_vision.FaceLandmarker.create_from_options(face_options) as face_detector,
            ):
                LOGGER.info("MediaPipe detectors initialized. Monitoring loop started.")
                last_camera_fail_log = 0.0
                while not self._stop_event.is_set():
                    rgb = frame_source.read_rgb()
                    if rgb is None:
                        self._set_state(status="camera_read_failed")
                        now = time.time()
                        if now - last_camera_fail_log > 3.0:
                            LOGGER.warning(
                                "Camera read failed (backend=%s). Retrying...",
                                frame_source.backend,
                            )
                            last_camera_fail_log = now
                        time.sleep(0.1)
                        continue

                    h, w = rgb.shape[:2]
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    ts_ms = int((time.monotonic() - start_ts) * 1000)

                    pose_result = pose_detector.detect_for_video(mp_img, ts_ms)
                    face_result = face_detector.detect_for_video(mp_img, ts_ms)
                    now = time.time()

                    if pose_result.pose_landmarks:
                        landmarks = pose_result.pose_landmarks[0]
                        nose = landmarks[0]
                        left_shoulder = landmarks[11]
                        right_shoulder = landmarks[12]

                        neck_x = (left_shoulder.x + right_shoulder.x) / 2
                        neck_y = (left_shoulder.y + right_shoulder.y) / 2

                        nose_np = np.array([nose.x * w, nose.y * h])
                        left_np = np.array([left_shoulder.x * w, left_shoulder.y * h])
                        right_np = np.array([right_shoulder.x * w, right_shoulder.y * h])
                        neck_np = np.array([neck_x * w, neck_y * h])

                        shoulder_width_pixels = float(np.linalg.norm(right_np - left_np))
                        inches_per_pixel = 17.0 / shoulder_width_pixels if shoulder_width_pixels > 50 else 0.0

                        vertical = np.array([0.0, -1.0])
                        head_vector = nose_np - neck_np
                        head_norm = np.linalg.norm(head_vector)
                        if head_norm > 1e-6:
                            cos_angle = float(np.dot(head_vector, vertical) / (head_norm * np.linalg.norm(vertical)))
                            cos_angle = float(np.clip(cos_angle, -1.0, 1.0))
                            head_tilt_angle = float(np.degrees(np.arccos(cos_angle)))
                        else:
                            head_tilt_angle = 0.0

                        shoulder_height_inches = float((right_np[1] - left_np[1]) * inches_per_pixel)
                        neck_to_nose = float(np.linalg.norm(nose_np - neck_np))
                        shoulder_width = float(np.linalg.norm(right_np - left_np))
                        normalized_head_distance = neck_to_nose / shoulder_width if shoulder_width > 0 else 0.0

                        if not posture_ready:
                            tilt_samples.append(head_tilt_angle)
                            shoulder_samples.append(shoulder_height_inches)
                            ratio_samples.append(normalized_head_distance)
                            if now - posture_calibration_start >= self.CALIBRATION_SECONDS:
                                baseline_tilt = float(np.mean(tilt_samples))
                                baseline_shoulder = float(np.mean(shoulder_samples))
                                baseline_ratio = float(np.mean(ratio_samples))
                                posture_ready = True
                                posture_prediction = "monitoring"
                        elif now - last_posture_sample_time >= self.POSTURE_SAMPLE_SECONDS:
                            tilt_denominator = baseline_tilt if abs(baseline_tilt) > 1e-6 else 1e-6
                            tilt_change = abs((head_tilt_angle - baseline_tilt) / tilt_denominator)
                            shoulder_change = abs(shoulder_height_inches - baseline_shoulder)
                            ratio_change = abs(normalized_head_distance - baseline_ratio)
                            features = [[tilt_change, shoulder_change, ratio_change]]
                            with warnings.catch_warnings():
                                warnings.filterwarnings(
                                    "ignore",
                                    message="X does not have valid feature names.*",
                                    category=UserWarning,
                                )
                                posture_prediction = str(posture_model.predict(features)[0]).lower()
                            posture_samples.append((now, posture_prediction == "bad"))
                            last_posture_sample_time = now

                    if face_result.face_landmarks:
                        last_face_seen_time = now
                        landmarks = face_result.face_landmarks[0]
                        pts = np.array([[lm.x * w, lm.y * h] for lm in landmarks], dtype=np.float32)
                        left_eye = pts[self.LEFT_EYE]
                        right_eye = pts[self.RIGHT_EYE]
                        ear = (self._compute_ear(left_eye) + self._compute_ear(right_eye)) / 2.0

                        if not eye_ready:
                            ear_samples.append(ear)
                            if now - eye_calibration_start >= self.CALIBRATION_SECONDS:
                                baseline_ear = float(np.mean(ear_samples)) if ear_samples else ear
                                eye_ready = True
                        else:
                            if ear < baseline_ear * self.EYE_CLOSED_THRESHOLD:
                                if not eye_closed:
                                    eye_closed = True
                                    closure_start = now
                            else:
                                if eye_closed:
                                    duration = now - closure_start
                                    blink_events.append((now, duration))
                                eye_closed = False
                    else:
                        # If face is lost while marked "eyes closed", end the closure event
                        # so the duration does not grow indefinitely.
                        if eye_closed and (now - last_face_seen_time) > self.FACE_LOST_RESET_SECONDS:
                            duration = max(0.0, last_face_seen_time - closure_start)
                            if duration > 0:
                                blink_events.append((now, duration))
                            eye_closed = False

                    while posture_samples and (now - posture_samples[0][0]) > self.HISTORY_WINDOW_SECONDS:
                        posture_samples.popleft()
                    while blink_events and (now - blink_events[0][0]) > self.HISTORY_WINDOW_SECONDS:
                        blink_events.popleft()

                    posture_count = len(posture_samples)
                    bad_count = sum(1 for _, is_bad in posture_samples if is_bad)
                    bad_ratio = (bad_count / posture_count) if posture_count else 0.0
                    bad_seconds = bad_ratio * self.HISTORY_WINDOW_SECONDS

                    blink_count = len(blink_events)
                    long_closures = [duration for _, duration in blink_events if duration >= self.LONG_CLOSURE_SECONDS]
                    long_closure_count = len(long_closures)
                    max_closure = max(long_closures) if long_closures else 0.0
                    if eye_closed and (now - last_face_seen_time) <= self.FACE_LOST_RESET_SECONDS:
                        latest_eye_closure = now - closure_start
                    else:
                        latest_eye_closure = 0.0

                    monitor_status = "calibrating"
                    if posture_ready and eye_ready:
                        monitor_status = "ready"
                    elif posture_ready:
                        monitor_status = "eye_calibrating"
                    elif eye_ready:
                        monitor_status = "posture_calibrating"

                    self._set_state(
                        monitoring_ready=posture_ready and eye_ready,
                        posture_ready=posture_ready,
                        eye_ready=eye_ready,
                        posture_prediction=posture_prediction,
                        bad_posture_ratio_60s=bad_ratio,
                        bad_posture_seconds_60s=bad_seconds,
                        blink_count_60s=blink_count,
                        long_closure_count_60s=long_closure_count,
                        max_closure_seconds_60s=max(max_closure, latest_eye_closure),
                        latest_eye_closure_seconds=latest_eye_closure,
                        status=monitor_status,
                        camera_backend=frame_source.backend,
                        accelerator_status=accelerator_status,
                        error=None,
                    )

        except Exception as exc:
            self._set_state(error=str(exc), status="error")
            LOGGER.exception("HealthMonitor crashed with an exception: %s", exc)
        finally:
            if frame_source is not None:
                frame_source.close()
