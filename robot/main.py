import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pygame
import requests
import sounddevice as sd


VOICE_ID = "PoHUWWWMHFrA8z7Q88pu"
ELEVEN_SAMPLE_RATE = 22050
MIC_SAMPLE_RATE = 16000
GROQ_CHAT_MODEL = "llama-3.3-70b-versatile"
GROQ_STT_MODEL = "whisper-large-v3-turbo"
WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 700
BACKGROUND_COLOR = (173, 216, 230)  # light blue
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
ALLOWED_FACES = {
    "anxious",
    "content",
    "defeated",
    "feisty",
    "frustrated",
    "gasping",
    "kissing",
    "laughing",
    "nervous",
    "relaxed",
    "sad",
    "shocked",
    "sweet",
    "teasing",
    "thrilled",
    "unimpressed",
    "worried",
    "yawning",
}
STOP_PHRASES = {
    "quit",
    "exit",
    "stop",
    "goodbye",
    "bye",
    "end conversation",
    "stop listening",
}

SILENCE_SECONDS_TO_STOP = 2.0
MIN_SPEECH_SECONDS = 0.2
MAX_UTTERANCE_SECONDS = 25.0
IDLE_TIMEOUT_SECONDS = 120.0
MIC_BLOCK_SECONDS = 0.05
MIC_NOISE_CALIBRATION_SECONDS = 0.6
MIC_PRE_ROLL_SECONDS = 0.5
MIC_MIN_START_THRESHOLD = 110.0
MIC_MAX_START_THRESHOLD = 700.0
MIC_START_MULTIPLIER = 2.6
MIC_CONTINUE_MULTIPLIER = 1.8
SPEAKING_FACE_SWITCH_SECONDS = 0.30


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


def choose_face_fallback(text: str) -> str:
    lowered = text.lower()
    keyword_map = [
        ("laughing", ["haha", "lol", "laugh", "funny", "hilarious", "joke"]),
        ("thrilled", ["amazing", "awesome", "great", "fantastic", "excited", "love"]),
        ("sweet", ["thanks", "thank you", "appreciate", "glad", "happy"]),
        ("sad", ["sad", "sorry", "unfortunately", "grief", "upset"]),
        ("worried", ["worry", "concern", "careful", "risk", "danger"]),
        ("frustrated", ["can't", "cannot", "error", "issue", "problem", "stuck"]),
        ("shocked", ["wow", "unbelievable", "surprising", "shocked"]),
        ("teasing", ["tease", "playful", "just kidding"]),
        ("yawning", ["tired", "sleepy", "rest", "exhausted"]),
    ]
    for face, keywords in keyword_map:
        if any(word in lowered for word in keywords):
            return face
    return "content"


def classify_user_face_with_groq(user_text: str, groq_api_key: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }
    face_list = ", ".join(sorted(ALLOWED_FACES))
    payload = {
        "model": GROQ_CHAT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return ONLY valid JSON with one key: 'face'. "
                    f"'face' must be exactly one of: {face_list}."
                ),
            },
            {
                "role": "user",
                "content": f"Pick the best face for this user utterance:\n{user_text}",
            },
        ],
        "temperature": 0.0,
        "max_tokens": 30,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code >= 400:
        return choose_face_fallback(user_text)

    try:
        content = response.json()["choices"][0]["message"]["content"].strip()
        face = str(json.loads(content).get("face", "")).strip().lower()
        if face in ALLOWED_FACES:
            return face
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        pass

    return choose_face_fallback(user_text)


class FaceDisplay:
    def __init__(self, faces_dir: Path):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption("Robot Face")
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
        else:
            print(f"Audio generated at: {path}")

    def close(self) -> None:
        pygame.quit()


def record_user_audio_until_silence(face_display: FaceDisplay) -> str | None:
    block_size = int(MIC_SAMPLE_RATE * MIC_BLOCK_SECONDS)
    silence_chunks_to_stop = max(1, int(SILENCE_SECONDS_TO_STOP / MIC_BLOCK_SECONDS))
    min_speech_chunks = max(1, int(MIN_SPEECH_SECONDS / MIC_BLOCK_SECONDS))
    max_chunks = max(1, int(MAX_UTTERANCE_SECONDS / MIC_BLOCK_SECONDS))
    idle_timeout_chunks = max(1, int(IDLE_TIMEOUT_SECONDS / MIC_BLOCK_SECONDS))
    calibration_chunks = max(1, int(MIC_NOISE_CALIBRATION_SECONDS / MIC_BLOCK_SECONDS))
    pre_roll_limit = max(1, int(MIC_PRE_ROLL_SECONDS / MIC_BLOCK_SECONDS))

    collected: list[np.ndarray] = []
    pre_roll: list[np.ndarray] = []
    speech_streak = 0
    silence_chunks = 0
    speech_started = False
    chunk_count = 0
    noise_rms_values: list[float] = []

    face_display.set_face("sweet")
    print("\nListening... (auto-detecting when you finish)")

    with sd.InputStream(
        samplerate=MIC_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=block_size,
    ) as stream:
        while True:
            if not face_display.handle_events():
                raise KeyboardInterrupt("Face window closed")

            audio_chunk, _ = stream.read(block_size)
            chunk_count += 1

            float_chunk = audio_chunk.astype(np.float32)
            rms = float(np.sqrt(np.mean(np.square(float_chunk))))
            if not speech_started:
                noise_rms_values.append(rms)
                if len(noise_rms_values) > calibration_chunks:
                    noise_rms_values.pop(0)

            noise_floor = (
                float(np.percentile(noise_rms_values, 60))
                if noise_rms_values
                else 0.0
            )
            start_threshold = min(
                MIC_MAX_START_THRESHOLD,
                max(MIC_MIN_START_THRESHOLD, noise_floor * MIC_START_MULTIPLIER),
            )
            continue_threshold = max(
                MIC_MIN_START_THRESHOLD * 0.65,
                noise_floor * MIC_CONTINUE_MULTIPLIER,
            )

            if not speech_started:
                pre_roll.append(audio_chunk.copy())
                if len(pre_roll) > pre_roll_limit:
                    pre_roll.pop(0)

                if rms >= start_threshold:
                    speech_streak += 1
                else:
                    speech_streak = 0

                if speech_streak >= min_speech_chunks:
                    speech_started = True
                    collected.extend(pre_roll)
                    silence_chunks = 0
                elif chunk_count >= idle_timeout_chunks:
                    return None
            else:
                collected.append(audio_chunk.copy())
                if rms >= continue_threshold:
                    silence_chunks = 0
                else:
                    silence_chunks += 1

                if silence_chunks >= silence_chunks_to_stop:
                    break
                if len(collected) >= max_chunks:
                    break

            face_display.clock.tick(60)

    if not speech_started or not collected:
        return None

    audio_data = np.concatenate(collected, axis=0).astype(np.int16)
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_file.close()

    with wave.open(temp_file.name, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(MIC_SAMPLE_RATE)
        wav_file.writeframes(audio_data.tobytes())

    return temp_file.name


def transcribe_with_groq(audio_path: str, groq_api_key: str) -> str:
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {groq_api_key}"}

    with open(audio_path, "rb") as f:
        files = {"file": (Path(audio_path).name, f, "audio/wav")}
        data = {
            "model": GROQ_STT_MODEL,
            "temperature": "0",
            "response_format": "json",
            "language": "en",
        }
        response = requests.post(url, headers=headers, data=data, files=files, timeout=60)

    if response.status_code >= 400:
        raise RuntimeError(f"Groq STT failed ({response.status_code}): {response.text}")

    return response.json().get("text", "").strip()


def chat_with_groq(messages: list[dict[str, str]], groq_api_key: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_CHAT_MODEL,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 300,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(f"Groq chat failed ({response.status_code}): {response.text}")

    try:
        return response.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Groq chat response: {response.text}") from exc


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


def should_stop_from_text(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if lowered in STOP_PHRASES:
        return True
    return any(phrase in lowered for phrase in STOP_PHRASES)


def main() -> None:
    load_dotenv()
    eleven_api_key = get_required_env("ELEVEN_LABS_API_KEY")
    groq_api_key = get_required_env("GROQ_API_KEY")
    faces_dir = Path(__file__).resolve().parent / "faces"
    face_display = FaceDisplay(faces_dir)

    print("Voice chat ready.")
    print("Always listening with auto end-of-speech detection.")
    print("Say 'quit', 'exit', or 'goodbye' to stop.")

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are a friendly voice assistant. Keep responses concise, natural, "
                "and easy to speak out loud."
            ),
        }
    ]

    while True:
        if not face_display.handle_events():
            print("Face window closed. Exiting.")
            break

        audio_path = None
        wav_path = None
        try:
            audio_path = record_user_audio_until_silence(face_display)
            if not audio_path:
                face_display.set_face("sweet")
                continue

            face_display.set_face("content")
            user_text = transcribe_with_groq(audio_path, groq_api_key)
            if not user_text:
                face_display.set_face("gasping")
                print("I didn't catch that. Listening again...")
                face_display.set_face("sweet")
                continue

            print(f"You: {user_text}")
            if should_stop_from_text(user_text):
                print("Stopping voice chat. Goodbye.")
                break

            detected_user_face = classify_user_face_with_groq(user_text, groq_api_key)
            face_display.hold_face(detected_user_face, 1.5)

            messages.append({"role": "user", "content": user_text})
            face_display.set_face("content")
            assistant_text = chat_with_groq(messages, groq_api_key)
            messages.append({"role": "assistant", "content": assistant_text})
            print(f"Assistant: {assistant_text}")

            face_display.set_face("content")
            pcm_data = synthesize_pcm(eleven_api_key, VOICE_ID, assistant_text)
            wav_path = write_wav(pcm_data)
            face_display.play_wav(wav_path, talk_faces=["sweet", "laughing"])
            face_display.set_face("sweet")
        except KeyboardInterrupt:
            print("\nStopped by keyboard interrupt.")
            break
        except Exception as exc:
            face_display.set_face("frustrated")
            print(f"Loop error: {exc}")
            print("Continuing...")
            time.sleep(0.5)
            face_display.set_face("sweet")
        finally:
            try:
                if audio_path:
                    Path(audio_path).unlink(missing_ok=True)
                if wav_path:
                    Path(wav_path).unlink(missing_ok=True)
            except OSError:
                pass

    face_display.close()


if __name__ == "__main__":
    main()
