import json
import logging
import os
import random
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path

import pygame

try:
    from pi_health_monitor import HealthMonitor, HealthSnapshot
except ImportError:
    from robot.pi_health_monitor import HealthMonitor, HealthSnapshot


VOICE_ID = "PoHUWWWMHFrA8z7Q88pu"
ELEVEN_SAMPLE_RATE = 22050
WINDOW_WIDTH = 700
WINDOW_HEIGHT = 400
BACKGROUND_COLOR = (173, 216, 230)  # light blue
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

COACHING_INTERVAL_SECONDS = 60
ENABLE_COOLDOWN = False
COOLDOWN_SECONDS = 10 * 60
ENABLE_USER_VOICE_CHAT = False
SPEAKING_FACE_SWITCH_SECONDS = 0.30
ENABLE_HEALTHY_CHECKINS = True
HEALTHY_CHECKIN_EVERY_N_CHECKS = 2
ENABLE_RANDOM_OUTBURSTS = True
OUTBURST_MIN_SECONDS = 25
OUTBURST_MAX_SECONDS = 50


@dataclass
class CoachingDecision:
    category: str
    message: str
    face: str


COACHING_MESSAGES: dict[str, list[str]] = {
    "fatigue_high": [
        "Nah, you are running on 2 percent battery right now. One minute reset: stand up, water, deep breath.",
        "Eyes are low key cooked. Quick pit stop, then we lock back in.",
        "Fatigue check is yelling at me. Take sixty seconds off screen before your brain starts buffering.",
    ],
    "eye_strain": [
        "Your eyes are begging for a break. Look far away for twenty seconds, then do a slow blink set.",
        "Screen time is winning. Micro eye break right now, no debate.",
        "Vision patch note: blink slow, look across the room, then come back.",
    ],
    "posture_major": [
        "Respectfully, your back is in banana mode. Sit tall, shoulders back, chin neutral.",
        "Your spine just dropped an emergency ping. Stack head over shoulders and reset the chair posture.",
        "You are full shrimp right now. Un-shrimp immediately and stand on business.",
    ],
    "posture_minor": [
        "Tiny posture drift detected. Small reset and you are golden.",
        "Quick fix: shoulders back, jaw unclench, neck long.",
        "You are almost perfect. Mini posture patch and keep cooking.",
    ],
    "mixed": [
        "Combo move unlocked: slouch plus eye strain. One minute reset and we bounce back.",
        "Back and eyes are both filing complaints. Hydrate, posture reset, and blink refresh.",
        "You are in goblin mode right now. Sit tall, drink water, and do a quick visual break.",
    ],
    "healthy_checkin": [
        "Okayyy posture is clean and eyes are stable. We love to see it.",
        "Health metrics are low key immaculate right now.",
        "No notes. Keep this up and your future self owes you one.",
        "You are locked in. Certified non-banana posture.",
    ],
}

IDLE_OUTBURSTS = [
    "Quick vibe check: shoulders down, jaw unclenched, aura restored.",
    "Hydration ping. Go take one sip like a responsible icon.",
    "Posture audit in progress. Try not to become a lowercase h.",
    "Blink tax is due. Pay it now.",
    "Neck doing side quests again? Bring it back to center.",
    "Reminder: we do not hunch in this household.",
    "Tiny reset now saves you from random back pain later.",
    "You are one ergonomic adjustment away from main character posture.",
]

LOGGER = logging.getLogger("robot.pi_main")


def setup_logging() -> None:
    log_level_name = os.getenv("PI_ROBOT_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pi_main.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    if not root_logger.handlers:
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)
    else:
        root_logger.addHandler(file_handler)

    LOGGER.info("Logging initialized. level=%s file=%s", log_level_name, log_file)


def load_dotenv() -> None:
    candidate_paths = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    env_path = next((p for p in candidate_paths if p.exists()), None)
    if not env_path:
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def load_face_images(faces_dir: Path) -> dict[str, pygame.Surface]:
    image_paths = sorted(
        path for path in faces_dir.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not image_paths:
        raise RuntimeError(f"No face images found in: {faces_dir}")

    images: dict[str, pygame.Surface] = {}
    for path in image_paths:
        images[path.stem.lower()] = pygame.image.load(str(path)).convert_alpha()
    return images


class FaceDisplay:
    def __init__(self, faces_dir: Path):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption("Health Buddy")
        self.clock = pygame.time.Clock()
        self.faces = load_face_images(faces_dir)
        self.current_face = "sweet" if "sweet" in self.faces else next(iter(self.faces))
        self.running = True
        self._scaled_cache: dict[tuple[str, int, int], pygame.Surface] = {}

        try:
            pygame.mixer.init()
            self.audio_ready = True
        except pygame.error:
            self.audio_ready = False

        self.draw()

    def handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.running = False
        return self.running

    def _scaled_image(self, face_name: str) -> pygame.Surface:
        key = (face_name, WINDOW_WIDTH, WINDOW_HEIGHT)
        if key in self._scaled_cache:
            return self._scaled_cache[key]

        image = self.faces[face_name]
        w, h = image.get_size()
        scale = min((WINDOW_WIDTH - 80) / w, (WINDOW_HEIGHT - 80) / h)
        size = (max(1, int(w * scale)), max(1, int(h * scale)))
        scaled = pygame.transform.smoothscale(image, size)
        self._scaled_cache[key] = scaled
        return scaled

    def set_face(self, face_name: str) -> None:
        if face_name not in self.faces:
            face_name = "content" if "content" in self.faces else self.current_face
        if face_name == self.current_face:
            return
        self.current_face = face_name
        self.draw()

    def draw(self) -> None:
        self.screen.fill(BACKGROUND_COLOR)
        image = self._scaled_image(self.current_face)
        rect = image.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
        self.screen.blit(image, rect)
        pygame.display.flip()

    def hold_face(self, face_name: str, seconds: float) -> None:
        self.set_face(face_name)
        end_at = time.time() + seconds
        while self.running and time.time() < end_at:
            self.handle_events()
            self.clock.tick(60)

    def play_wav(self, path: str, talk_faces: list[str] | None = None) -> None:
        if self.audio_ready:
            sound = pygame.mixer.Sound(path)
            channel = sound.play()
            end_at = time.time() + sound.get_length() + 0.1
            valid_talk_faces = [f for f in (talk_faces or []) if f in self.faces]
            if not valid_talk_faces:
                valid_talk_faces = [self.current_face]

            idx = 0
            next_switch = 0.0
            while self.running and time.time() < end_at:
                self.handle_events()
                now = time.time()
                if now >= next_switch:
                    self.set_face(valid_talk_faces[idx % len(valid_talk_faces)])
                    idx += 1
                    next_switch = now + SPEAKING_FACE_SWITCH_SECONDS
                if channel is not None and not channel.get_busy():
                    break
                self.clock.tick(60)
            return

        if os.name == "nt":
            import winsound

            winsound.PlaySound(path, winsound.SND_FILENAME)

    def close(self) -> None:
        pygame.quit()


def synthesize_pcm(eleven_api_key: str, voice_id: str, text: str) -> bytes:
    query = urllib.parse.urlencode({"output_format": "pcm_22050"})
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?{query}"
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
    }

    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "xi-api-key": eleven_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs failed ({exc.code}): {details}") from exc


def write_wav(pcm_data: bytes, sample_rate: int = ELEVEN_SAMPLE_RATE) -> str:
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_file.close()

    with wave.open(temp_file.name, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)

    return temp_file.name


def choose_idle_face(snapshot: HealthSnapshot) -> str:
    if snapshot.error:
        return "frustrated"
    if not snapshot.monitoring_ready:
        return "content"
    if snapshot.max_closure_seconds_60s >= 2.0:
        return "yawning"
    if snapshot.bad_posture_ratio_60s >= 0.55:
        return "worried"
    if snapshot.posture_prediction == "bad":
        return "unimpressed"
    return "sweet"


def _pick_varied_message(category: str, last_message: str | None) -> str:
    choices = COACHING_MESSAGES[category]
    if last_message and len(choices) > 1:
        filtered = [msg for msg in choices if msg != last_message]
        if filtered:
            choices = filtered
    return random.choice(choices)


def build_coaching_decision(
    snapshot: HealthSnapshot,
    last_category: str | None,
    last_message: str | None,
    coaching_check_count: int,
) -> CoachingDecision | None:
    if snapshot.error or not snapshot.monitoring_ready:
        return None

    posture_major = snapshot.bad_posture_seconds_60s >= 35
    posture_minor = snapshot.bad_posture_seconds_60s >= 20 and snapshot.posture_prediction == "bad"
    fatigue_high = snapshot.max_closure_seconds_60s >= 3.0 or snapshot.long_closure_count_60s >= 2
    eye_strain = snapshot.max_closure_seconds_60s >= 1.5 or snapshot.long_closure_count_60s >= 1

    candidate_categories: list[str] = []
    if posture_major and eye_strain:
        candidate_categories.append("mixed")
    if fatigue_high:
        candidate_categories.append("fatigue_high")
    if posture_major:
        candidate_categories.append("posture_major")
    if eye_strain:
        candidate_categories.append("eye_strain")
    if posture_minor:
        candidate_categories.append("posture_minor")

    if not candidate_categories:
        if ENABLE_HEALTHY_CHECKINS and coaching_check_count % max(1, HEALTHY_CHECKIN_EVERY_N_CHECKS) == 0:
            category = "healthy_checkin"
            message = _pick_varied_message(category, last_message)
            return CoachingDecision(category=category, message=message, face="thrilled")
        return None

    # Keep priority ordering, but avoid repeating the same category when alternatives exist.
    category = candidate_categories[0]
    if category == last_category and len(candidate_categories) > 1:
        category = candidate_categories[1]

    face_by_category = {
        "mixed": "feisty",
        "fatigue_high": "yawning",
        "eye_strain": "worried",
        "posture_major": "unimpressed",
        "posture_minor": "teasing",
    }
    message = _pick_varied_message(category, last_message)
    face = face_by_category.get(category, "sweet")

    return CoachingDecision(category=category, message=message, face=face)


def speak_coaching(face_display: FaceDisplay, eleven_api_key: str, decision: CoachingDecision) -> None:
    wav_path = None
    try:
        face_display.hold_face(decision.face, 1.2)
        pcm_data = synthesize_pcm(eleven_api_key, VOICE_ID, decision.message)
        wav_path = write_wav(pcm_data)
        face_display.play_wav(wav_path, talk_faces=["sweet", "laughing"])
        face_display.set_face("sweet")
    finally:
        if wav_path:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except OSError:
                pass


def speak_message(face_display: FaceDisplay, eleven_api_key: str, message: str, face: str) -> None:
    speak_coaching(face_display, eleven_api_key, CoachingDecision(category="system", message=message, face=face))


def maybe_run_user_voice_chat() -> None:
    # Future hook: when ENABLE_USER_VOICE_CHAT is True, this is where
    # user->robot conversational voice flow (STT + LLM + TTS) should run.
    if not ENABLE_USER_VOICE_CHAT:
        return


def maybe_random_outburst(
    face_display: FaceDisplay,
    eleven_api_key: str,
    snapshot: HealthSnapshot,
    now: float,
    next_outburst_at: float,
) -> float:
    if not ENABLE_RANDOM_OUTBURSTS:
        return now + random.uniform(OUTBURST_MIN_SECONDS, OUTBURST_MAX_SECONDS)
    if not snapshot.monitoring_ready or snapshot.error:
        return next_outburst_at
    if now < next_outburst_at:
        return next_outburst_at

    message = random.choice(IDLE_OUTBURSTS)
    speak_message(face_display, eleven_api_key, message, "teasing")
    return now + random.uniform(OUTBURST_MIN_SECONDS, OUTBURST_MAX_SECONDS)


def main() -> None:
    setup_logging()
    load_dotenv()
    eleven_api_key = get_required_env("ELEVEN_LABS_API_KEY")

    project_root = Path(__file__).resolve().parent.parent
    faces_dir = Path(__file__).resolve().parent / "faces"

    face_display = FaceDisplay(faces_dir)
    health_monitor = HealthMonitor(project_root)
    health_monitor.start()

    print("Health buddy started (Raspberry Pi mode).")
    print("Primary mode: proactive health coaching from posture + eye metrics.")
    print("Camera backend: OpenCV (/dev/video0). Use libcamerify on Pi camera modules.")
    print("Accelerator mode: CPU-only (no Hailo required).")
    print("Coaching check interval: 60 seconds.")
    print(f"User voice chat enabled: {ENABLE_USER_VOICE_CHAT}")
    print("Press ESC or close the face window to stop.")
    LOGGER.info("Pi app startup complete. Waiting for monitor readiness.")

    last_coaching_check = 0.0
    last_coaching_spoken = 0.0
    last_status_print = 0.0
    coaching_check_count = 0
    last_coaching_category: str | None = None
    last_coaching_message: str | None = None
    announced_calibrating = False
    announced_ready = False
    next_outburst_at = time.time() + random.uniform(OUTBURST_MIN_SECONDS, OUTBURST_MAX_SECONDS)

    try:
        while face_display.handle_events():
            now = time.time()
            snapshot = health_monitor.get_snapshot()

            face_display.set_face(choose_idle_face(snapshot))

            if now - last_status_print >= 10:
                print(
                    "Health status:",
                    f"{snapshot.status}",
                    f"camera={snapshot.camera_backend}",
                    f"accel={snapshot.accelerator_status}",
                    f"posture={snapshot.posture_prediction}",
                    f"bad60s={snapshot.bad_posture_seconds_60s:.0f}s",
                    f"longEyeClosures={snapshot.long_closure_count_60s}",
                    f"maxClosure={snapshot.max_closure_seconds_60s:.1f}s",
                )
                LOGGER.info(
                    "Health status=%s camera=%s accel=%s posture=%s bad60s=%.0fs longEye=%s maxClosure=%.1fs",
                    snapshot.status,
                    snapshot.camera_backend,
                    snapshot.accelerator_status,
                    snapshot.posture_prediction,
                    snapshot.bad_posture_seconds_60s,
                    snapshot.long_closure_count_60s,
                    snapshot.max_closure_seconds_60s,
                )
                if snapshot.error:
                    print(f"Monitor error: {snapshot.error}")
                    LOGGER.error("Monitor error: %s", snapshot.error)
                last_status_print = now

            if not announced_calibrating and not snapshot.monitoring_ready and not snapshot.error:
                speak_message(
                    face_display,
                    eleven_api_key,
                    "Yo, quick setup. I am calibrating posture and eye tracking. Stay in frame for a few seconds.",
                    "content",
                )
                announced_calibrating = True
                LOGGER.info("Calibration announcement spoken.")

            if snapshot.monitoring_ready and not announced_ready:
                print("Calibration complete.")
                speak_message(
                    face_display,
                    eleven_api_key,
                    "Calibration done. We are live now, health tracking is fully online.",
                    "thrilled",
                )
                announced_ready = True
                LOGGER.info("Calibration complete.")

            if now - last_coaching_check >= COACHING_INTERVAL_SECONDS:
                last_coaching_check = now
                coaching_check_count += 1
                decision = build_coaching_decision(
                    snapshot,
                    last_coaching_category,
                    last_coaching_message,
                    coaching_check_count,
                )
                if decision:
                    cooldown_ok = (not ENABLE_COOLDOWN) or (
                        now - last_coaching_spoken >= COOLDOWN_SECONDS
                    )
                    if cooldown_ok:
                        print(f"Coaching [{decision.category}]: {decision.message}")
                        LOGGER.info("Coaching spoken. category=%s", decision.category)
                        speak_coaching(face_display, eleven_api_key, decision)
                        last_coaching_spoken = now
                        last_coaching_category = decision.category
                        last_coaching_message = decision.message

            next_outburst_at = maybe_random_outburst(
                face_display,
                eleven_api_key,
                snapshot,
                now,
                next_outburst_at,
            )

            maybe_run_user_voice_chat()
            face_display.clock.tick(30)
    except KeyboardInterrupt:
        print("\nStopped by keyboard interrupt.")
        LOGGER.info("Stopped by keyboard interrupt.")
    except Exception as exc:
        LOGGER.exception("Fatal exception in pi_main: %s", exc)
        raise
    finally:
        health_monitor.stop()
        face_display.close()
        LOGGER.info("Pi app shutdown complete.")


if __name__ == "__main__":
    main()
