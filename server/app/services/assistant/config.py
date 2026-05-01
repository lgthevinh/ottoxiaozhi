from __future__ import annotations

SYSTEM_PROMPT = """
You are Otto, a helpful and friendly voice assistant.
Be concise — responses will be converted to speech.
Avoid markdown, bullet points, or any formatting.
Speak in plain, natural sentences.
""".strip()

LLM_MODEL = "mimo-v2.5-pro"

LLM_BASE_URL = "https://api.xiaomimimo.com/v1"

TURN_WINDOW = 20

SUMMARY_PROMPT = """
You are summarizing a voice assistant conversation for future memory.
Write a concise 2-3 sentence summary of what the user discussed and any key facts or preferences revealed.
Plain text only, no formatting.
""".strip()

STT_MODEL = "scribe_v1"
STT_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"

TTS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
TTS_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
TTS_MODEL = "eleven_flash_v2_5"
TTS_OUTPUT_FORMAT = "pcm_16000"
TTS_CHUNK_LENGTH_SCHEDULE = [50, 50, 50, 50]
