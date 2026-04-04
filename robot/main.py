import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd


VOICE_ID = "PoHUWWWMHFrA8z7Q88pu"
ELEVEN_SAMPLE_RATE = 22050
MIC_SAMPLE_RATE = 16000
RECORD_SECONDS = 6
GROQ_CHAT_MODEL = "llama-3.3-70b-versatile"
GROQ_STT_MODEL = "whisper-large-v3-turbo"


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


def record_user_audio(seconds: int = RECORD_SECONDS) -> str:
    print(f"\nListening for {seconds} seconds...")
    frames = sd.rec(
        int(seconds * MIC_SAMPLE_RATE),
        samplerate=MIC_SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    print("Recording complete.")

    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_file.close()

    with wave.open(temp_file.name, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(MIC_SAMPLE_RATE)
        wav_file.writeframes(np.asarray(frames, dtype=np.int16).tobytes())

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

    transcript = response.json().get("text", "").strip()
    return transcript


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


def play_wav(path: str) -> None:
    if os.name == "nt":
        import winsound

        winsound.PlaySound(path, winsound.SND_FILENAME)
    else:
        print(f"Audio generated at: {path}")


def main() -> None:
    load_dotenv()
    eleven_api_key = get_required_env("ELEVEN_LABS_API_KEY")
    groq_api_key = get_required_env("GROQ_API_KEY")

    print("Voice chat ready.")
    print("Press ENTER to talk, or type q then ENTER to quit.")

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
        user_control = input("\n[ENTER]=speak, q=quit: ").strip().lower()
        if user_control in {"q", "quit", "exit"}:
            print("Goodbye.")
            break

        audio_path = record_user_audio()
        user_text = transcribe_with_groq(audio_path, groq_api_key)
        if not user_text:
            print("I didn't catch that. Please try again.")
            continue

        print(f"You: {user_text}")
        messages.append({"role": "user", "content": user_text})

        assistant_text = chat_with_groq(messages, groq_api_key)
        messages.append({"role": "assistant", "content": assistant_text})
        print(f"Assistant: {assistant_text}")

        pcm_data = synthesize_pcm(eleven_api_key, VOICE_ID, assistant_text)
        wav_path = write_wav(pcm_data)
        play_wav(wav_path)


if __name__ == "__main__":
    main()
