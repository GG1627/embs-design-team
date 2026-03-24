# Import libraries
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import numpy as np
import urllib.request
import time
from pathlib import Path

# ---------------- Model Setup ----------------

MODEL_PATH = "face_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/latest/"
    "face_landmarker.task"
)

def download_model():
    if not Path(MODEL_PATH).exists():
        print("Downloading face model...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("Model ready.")

# ---------------- Video Setup ----------------

cap = cv2.VideoCapture(0)
fps = cap.get(cv2.CAP_PROP_FPS)
if fps == 0:
    fps = 30

delay = int(1000 / fps)

download_model()

# ---------------- Face Landmarker ----------------

options = mp_vision.FaceLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=mp_vision.RunningMode.VIDEO,
    num_faces=1,
)

start_ts = time.monotonic()

# -------- Calibration --------

CALIBRATION_TIME = 10
calibration_start = time.time()
baseline_ready = False

ear_samples = []
baseline_ear = 0

# -------- Variables --------

eye_closed = False
closure_start_time = 0

blink_duration = 0
eye_closure_time = 0
ear_change = 0

EYE_CLOSED_THRESHOLD = 0.75

status = "Calibrating..."

# -------- Eye Landmarks --------

LEFT_EYE  = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

def compute_ear(eye):
    A = np.linalg.norm(eye[1] - eye[5])
    B = np.linalg.norm(eye[2] - eye[4])
    C = np.linalg.norm(eye[0] - eye[3])
    return (A + B) / (2.0 * C)

# ---------------- Main Loop ----------------

with mp_vision.FaceLandmarker.create_from_options(options) as detector:

    while True:

        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.resize(frame, (1280, 720))
        h, w = frame.shape[:2]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        ts_ms = int((time.monotonic() - start_ts) * 1000)
        result = detector.detect_for_video(mp_img, ts_ms)

        if result.face_landmarks:

            landmarks = result.face_landmarks[0]
            pts = np.array([[int(lm.x*w), int(lm.y*h)] for lm in landmarks])

            left_eye = pts[LEFT_EYE]
            right_eye = pts[RIGHT_EYE]

            left_ear = compute_ear(left_eye)
            right_ear = compute_ear(right_eye)
            ear = (left_ear + right_ear) / 2

            current_time = time.time()

            # -------- CALIBRATION --------
            if not baseline_ready:
                ear_samples.append(ear)

                if current_time - calibration_start >= CALIBRATION_TIME:
                    baseline_ear = np.mean(ear_samples)
                    baseline_ready = True
                    status = "Tracking..."

            # -------- EYE TRACKING --------
            if baseline_ready:

                ear_change = abs(ear - baseline_ear)

                # Eyes closed
                if ear < baseline_ear * EYE_CLOSED_THRESHOLD:

                    if not eye_closed:
                        eye_closed = True
                        closure_start_time = current_time

                    eye_closure_time = current_time - closure_start_time

                else:
                    # Eyes reopened → BLINK EVENT

                    if eye_closed:

                        blink_duration = current_time - closure_start_time

                        # -------- PRINT SAMPLE --------
                        print("\n============= BLINK DETECTED =============")
                        print(f"Time: {time.strftime('%H:%M:%S')}")
                        print("------------------------------------------")
                        print(f"EAR Change         : {ear_change:.4f}")
                        print(f"Blink Duration     : {blink_duration:.3f} sec")
                        print(f"Eye Closure Time   : {blink_duration:.3f} sec")
                        print("==========================================\n")

                    eye_closed = False
                    eye_closure_time = 0

            # -------- DRAW --------
            for p in left_eye:
                cv2.circle(frame, tuple(p), 2, (0,255,0), -1)
            for p in right_eye:
                cv2.circle(frame, tuple(p), 2, (0,255,0), -1)

        # -------- DISPLAY --------

        # LEFT: Baseline
        if baseline_ready:
            cv2.putText(frame, "BASELINE EAR", (20,40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255),2)

            cv2.putText(frame, f"EAR: {baseline_ear:.3f}",
                        (20,80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0),2)
        else:
            cv2.putText(frame, "CALIBRATING...", (20,40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,255),2)

        # RIGHT: LIVE FEATURES
        right_x = w - 350

        cv2.putText(frame, "LIVE FEATURES", (right_x,40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255),2)

        cv2.putText(frame, f"EAR Change: {ear_change:.3f}",
                    (right_x,80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255),2)

        cv2.putText(frame, f"Blink Duration: {blink_duration:.2f}s",
                    (right_x,110), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255),2)

        cv2.putText(frame, f"Closure Time: {eye_closure_time:.2f}s",
                    (right_x,140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255),2)

        # CENTER
        cv2.putText(frame, f"Status: {status}",
                    (w//2 - 150, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0,0,255),
                    3)

        cv2.imshow("Blink-Based Data Collection", frame)

        if cv2.waitKey(delay) & 0xFF == 27:
            break

cap.release()
cv2.destroyAllWindows()