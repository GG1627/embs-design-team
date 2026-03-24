# Posture_Detection_Code

# Import necessary libraries
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import numpy as np
import urllib.request
import time
from pathlib import Path
import joblib

model = joblib.load("posture_model.pkl")

# ---------------- Model Setup ----------------

MODEL_PATH = "pose_landmarker_lite.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/latest/"
    "pose_landmarker_lite.task"
)

def download_model():
    if not Path(MODEL_PATH).exists():
        print("Downloading pose landmark model (~5 MB)...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("Model ready.")

# ---------------- Video Input ----------------

cap = cv2.VideoCapture(0)
fps = cap.get(cv2.CAP_PROP_FPS)
if fps == 0:
    fps = 30

delay = int(1000 / fps)

# ---------------- MediaPipe Setup ----------------

download_model()

options = mp_vision.PoseLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=mp_vision.RunningMode.VIDEO,
    num_poses=1,
    min_pose_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

start_ts = time.monotonic()

# -------- Calibration Setup ----------

CALIBRATION_TIME = 10
calibration_start = time.time()
baseline_ready = False

tilt_samples = []
shoulder_samples = []
ratio_samples = []

baseline_tilt = 0
baseline_shoulder = 0
baseline_ratio = 0

# -------- Other Variables ----------

last_sample_time = 0
tilt_change = 0
shoulder_change = 0
ratio_change = 0

prediction = "Calibrating..."

# ---------------- Main Loop ----------------

with mp_vision.PoseLandmarker.create_from_options(options) as detector:

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

        if result.pose_landmarks:

            landmarks = result.pose_landmarks[0]

            # Extract landmarks
            nose = landmarks[0]
            left_shoulder = landmarks[11]
            right_shoulder = landmarks[12]

            # Neck midpoint
            neck_x = (left_shoulder.x + right_shoulder.x) / 2
            neck_y = (left_shoulder.y + right_shoulder.y) / 2

            # Pixel coordinates
            nose_pt = (int(nose.x * w), int(nose.y * h))
            left_pt = (int(left_shoulder.x * w), int(left_shoulder.y * h))
            right_pt = (int(right_shoulder.x * w), int(right_shoulder.y * h))
            neck_pt = (int(neck_x * w), int(neck_y * h))

            # Arrays
            nose_np = np.array(nose_pt)
            neck_np = np.array(neck_pt)
            left_np = np.array(left_pt)
            right_np = np.array(right_pt)

            shoulder_width_pixels = np.linalg.norm(right_np - left_np)

            if shoulder_width_pixels > 50:
                inches_per_pixel = 17.0 / shoulder_width_pixels
            else:
                inches_per_pixel = 0

            # Head tilt
            vertical = np.array([0, -1])
            head_vector = nose_np - neck_np

            cos_angle = np.dot(head_vector, vertical) / (
                np.linalg.norm(head_vector) * np.linalg.norm(vertical)
            )
            head_tilt_angle = np.degrees(np.arccos(cos_angle))

            # Shoulder difference
            shoulder_height_inches = (right_np[1] - left_np[1]) * inches_per_pixel

            # Head ratio
            neck_to_nose = np.linalg.norm(nose_np - neck_np)
            shoulder_width = np.linalg.norm(right_np - left_np)

            if shoulder_width > 0:
                normalized_head_distance = neck_to_nose / shoulder_width
            else:
                normalized_head_distance = 0

            # -------- CALIBRATION --------

            current_time = time.time()

            if not baseline_ready:

                tilt_samples.append(head_tilt_angle)
                shoulder_samples.append(shoulder_height_inches)
                ratio_samples.append(normalized_head_distance)

                if current_time - calibration_start >= CALIBRATION_TIME:

                    baseline_tilt = np.mean(tilt_samples)
                    baseline_shoulder = np.mean(shoulder_samples)
                    baseline_ratio = np.mean(ratio_samples)

                    baseline_ready = True
                    last_sample_time = current_time
                    prediction = "Monitoring..."

            # -------- SAMPLING --------

            if baseline_ready and current_time - last_sample_time >= 15:

                tilt_change = abs((head_tilt_angle - baseline_tilt) / baseline_tilt)
                shoulder_change = abs(shoulder_height_inches - baseline_shoulder)
                ratio_change = abs(normalized_head_distance - baseline_ratio)

                features = [[tilt_change, shoulder_change, ratio_change]]
                prediction = model.predict(features)[0]

                last_sample_time = current_time

            # -------- DRAW --------

            cv2.circle(frame, nose_pt, 8, (0,255,0), -1)
            cv2.circle(frame, left_pt, 8, (255,0,0), -1)
            cv2.circle(frame, right_pt, 8, (255,0,0), -1)
            cv2.circle(frame, neck_pt, 8, (0,0,255), -1)

            cv2.line(frame, nose_pt, neck_pt, (0,255,255), 2)
            cv2.line(frame, left_pt, right_pt, (255,255,0), 2)

        # -------- DISPLAY --------

        # LEFT: Baseline
        if baseline_ready:
            cv2.putText(frame, "BASELINE", (20,40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255),2)

            cv2.putText(frame, f"Tilt: {baseline_tilt:.2f} deg",
                        (20,80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0),2)

            cv2.putText(frame, f"Shoulder: {baseline_shoulder:.2f} in",
                        (20,110), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0),2)

            cv2.putText(frame, f"Head Ratio: {baseline_ratio:.3f}",
                        (20,140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0),2)
        else:
            cv2.putText(frame, "CALIBRATING...", (20,40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,255),2)

        # RIGHT: Current posture
        if result.pose_landmarks:
            right_x = w - 320

            cv2.putText(frame, "CURRENT POSTURE", (right_x,40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255),2)

            cv2.putText(frame, f"Tilt: {head_tilt_angle:.2f} deg",
                        (right_x,80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255),2)

            cv2.putText(frame, f"Shoulder: {shoulder_height_inches:.2f} in",
                        (right_x,110), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255),2)

            cv2.putText(frame, f"Head Ratio: {normalized_head_distance:.3f}",
                        (right_x,140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255),2)

        # CENTER: Prediction
        cv2.putText(frame, f"Posture: {prediction}",
                    (w//2 - 120, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0,0,255),
                    3)

        cv2.imshow("Posture Detection", frame)

        if cv2.waitKey(delay) & 0xFF == 27:
            break

cap.release()
cv2.destroyAllWindows()