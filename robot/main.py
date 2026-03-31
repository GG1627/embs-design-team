import cv2
import pyttsx3
import numpy as np

# ----------------------------
# Text-to-speech setup
# ----------------------------
engine = pyttsx3.init()

def speak(text):
    engine.say(text)
    engine.runAndWait()

# ----------------------------
# Load base robot face
# ----------------------------
image = cv2.imread("./robot/Face.png")

if image is None:
    print("Error: Face.png not found")
    exit()

state = "neutral"

# Cyan color similar to example image (OpenCV uses BGR)
FACE_COLOR = (230, 255, 0)

def draw_face(base_img, state):
    """
    Draw robot facial features on top of the blank gray face base.
    Designed to look closer to the example image.
    """
    img = base_img.copy()
    h, w, _ = img.shape

    # ----------------------------
    # Main feature placement
    # ----------------------------
    left_eye = (int(w * 0.38), int(h * 0.42))
    right_eye = (int(w * 0.62), int(h * 0.42))

    eye_radius = int(min(w, h) * 0.045)

    mouth_center = (int(w * 0.50), int(h * 0.60))
    mouth_axes = (int(w * 0.16), int(h * 0.11))

    # ----------------------------
    # Helper functions
    # ----------------------------
    def draw_round_eyes():
        cv2.circle(img, left_eye, eye_radius, FACE_COLOR, -1)
        cv2.circle(img, right_eye, eye_radius, FACE_COLOR, -1)

    def draw_smile():
        cv2.ellipse(
            img,
            mouth_center,
            mouth_axes,
            0,
            20,
            160,
            FACE_COLOR,
            12
        )

    def draw_neutral_mouth():
        cv2.line(
            img,
            (int(w * 0.40), int(h * 0.63)),
            (int(w * 0.60), int(h * 0.63)),
            FACE_COLOR,
            10
        )

    def draw_small_frown():
        cv2.ellipse(
            img,
            (int(w * 0.50), int(h * 0.72)),
            (int(w * 0.10), int(h * 0.04)),
            0,
            200,
            340,
            FACE_COLOR,
            8
        )

    # ----------------------------
    # NEUTRAL
    # ----------------------------
    if state == "neutral":
        draw_round_eyes()
        draw_neutral_mouth()

    # ----------------------------
    # HAPPY
    # ----------------------------
    elif state == "happy":
        draw_round_eyes()
        draw_smile()

    # ----------------------------
    # SIDE-EYE
    # ----------------------------
    elif state == "side_eye":
        # eye outlines
        cv2.ellipse(img, left_eye, (eye_radius + 12, eye_radius - 2), 0, 0, 360, FACE_COLOR, 4)
        cv2.ellipse(img, right_eye, (eye_radius + 12, eye_radius - 2), 0, 0, 360, FACE_COLOR, 4)

        # pupils pushed to the right for suspicious look
        cv2.circle(img, (left_eye[0] + 12, left_eye[1]), 8, FACE_COLOR, -1)
        cv2.circle(img, (right_eye[0] + 12, right_eye[1]), 8, FACE_COLOR, -1)

        # one eyebrow slightly lowered
        cv2.line(
            img,
            (left_eye[0] - 18, left_eye[1] - 28),
            (left_eye[0] + 18, left_eye[1] - 22),
            FACE_COLOR,
            4
        )
        cv2.line(
            img,
            (right_eye[0] - 18, right_eye[1] - 20),
            (right_eye[0] + 18, right_eye[1] - 28),
            FACE_COLOR,
            4
        )

        # crooked mouth
        cv2.line(
            img,
            (int(w * 0.42), int(h * 0.64)),
            (int(w * 0.59), int(h * 0.62)),
            FACE_COLOR,
            8
        )

    # ----------------------------
    # PANIC
    # ----------------------------
    elif state == "panic":
        # big alarmed eyes
        cv2.circle(img, left_eye, eye_radius + 8, FACE_COLOR, 5)
        cv2.circle(img, right_eye, eye_radius + 8, FACE_COLOR, 5)

        cv2.circle(img, left_eye, 7, FACE_COLOR, -1)
        cv2.circle(img, right_eye, 7, FACE_COLOR, -1)

        # eyebrows raised
        cv2.line(
            img,
            (left_eye[0] - 20, left_eye[1] - 35),
            (left_eye[0] + 20, left_eye[1] - 28),
            FACE_COLOR,
            4
        )
        cv2.line(
            img,
            (right_eye[0] - 20, right_eye[1] - 28),
            (right_eye[0] + 20, right_eye[1] - 35),
            FACE_COLOR,
            4
        )

        # open mouth
        cv2.ellipse(
            img,
            (int(w * 0.50), int(h * 0.66)),
            (20, 32),
            0,
            0,
            360,
            FACE_COLOR,
            6
        )

    # ----------------------------
    # FAINT
    # ----------------------------
    elif state == "faint":
        # drooping eyes
        cv2.ellipse(img, left_eye, (22, 10), 0, 200, 340, FACE_COLOR, 5)
        cv2.ellipse(img, right_eye, (22, 10), 0, 200, 340, FACE_COLOR, 5)

        # dazed x eyes
        cv2.line(
            img,
            (left_eye[0] - 8, left_eye[1] - 8),
            (left_eye[0] + 8, left_eye[1] + 8),
            FACE_COLOR,
            3
        )
        cv2.line(
            img,
            (left_eye[0] + 8, left_eye[1] - 8),
            (left_eye[0] - 8, left_eye[1] + 8),
            FACE_COLOR,
            3
        )
        cv2.line(
            img,
            (right_eye[0] - 8, right_eye[1] - 8),
            (right_eye[0] + 8, right_eye[1] + 8),
            FACE_COLOR,
            3
        )
        cv2.line(
            img,
            (right_eye[0] + 8, right_eye[1] - 8),
            (right_eye[0] - 8, right_eye[1] + 8),
            FACE_COLOR,
            3
        )

        # weak droopy mouth
        draw_small_frown()

    return img


print("Controls:")
print("n = neutral")
print("h = happy")
print("s = side-eye")
print("p = panic")
print("f = faint")
print("q = quit")

speak("Hello. I am your wellness robot.")

while True:
    face = draw_face(image, state)
    cv2.imshow("Robot Face", face)

    key = cv2.waitKey(1) & 0xFF

    if key == ord('q'):
        break
    elif key == ord('n'):
        state = "neutral"
        speak("Neutral mode.")
    elif key == ord('h'):
        state = "happy"
        speak("I am feeling happy.")
    elif key == ord('s'):
        state = "side_eye"
        speak("Hmm... suspicious.")
    elif key == ord('p'):
        state = "panic"
        speak("Warning! Something is wrong!")
    elif key == ord('f'):
        state = "faint"
        speak("System overload... shutting down.")

cv2.destroyAllWindows()