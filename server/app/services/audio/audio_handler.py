from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List

from app.services.audio.audio_config import AudioConstants
from app.services.audio.audio_session import AudioSession


@dataclass
class AudioFrame:
    index: int
    data: bytes


class AudioHandler:
    # Session per device connected via websocket, keyed by session_id
    verify_audio_session: AudioSession
    verify_audio_bytes: bytes

    pink_audio_bytes: bytes
    ws_audio_session: dict[str, AudioSession] = {}
    
    def __init__(self) -> None:
        # Create a default session for sending initial audio for verification on every websocket connection
        self.verify_audio_session = self._create_session()
        self._load_verify_audio_bytes()
        self._load_pink_audio_bytes()
    
    def get_verify_session(self) -> AudioSession:
        return self.verify_audio_session
    
    def get_session(self, session_id: str) -> AudioSession | None:
        if session_id is None:
            return None
        if session_id not in self.ws_audio_session:
            return self._create_session(session_id)
        return self.ws_audio_session.get(session_id)
    
    def _create_session(self, session_id: str | None = None) -> AudioSession:
        if session_id is None:
            return None
        session = AudioSession(session_id=session_id, created_at=datetime.now(timezone.utc))
        self.ws_audio_session[session_id] = session
        return session
    
    def send_verify_audio(self, session_id: str) -> Iterable[bytes]:
        print(f"Sending verify audio for session {session_id}")
        session = self.get_session(session_id)
        if not session:
            return
        if not session.pending_bytes:
            session.pending_bytes = self.verify_audio_bytes
        while session.pending_bytes:
            pcm_data = session.pending_bytes[:AudioConstants.BYTES_PER_SAMPLE]
            session.pending_bytes = session.pending_bytes[AudioConstants.BYTES_PER_SAMPLE:]
            yield bytes([AudioConstants.PACKET_START]) + pcm_data + bytes([AudioConstants.PACKET_END])
    
    def send_pink_audio(self, session_id: str) -> Iterable[bytes]:
        print(f"Sending pink audio for session {session_id}")
        session = self.get_session(session_id)
        if not session:
            return
        pink_bytes = self.pink_audio_bytes
        session.pending_bytes = pink_bytes
        while session.pending_bytes:
            pcm_data = session.pending_bytes[:AudioConstants.BYTES_PER_SAMPLE]
            session.pending_bytes = session.pending_bytes[AudioConstants.BYTES_PER_SAMPLE:]
            yield bytes([AudioConstants.PACKET_START]) + pcm_data + bytes([AudioConstants.PACKET_END])

    def _process_audio_chunk(self, pcm_bytes: bytes) -> List[AudioFrame]:
        if not pcm_bytes:
            return []

        session = self.verify_audio_session
        session.pending_bytes += pcm_bytes
        frames: List[AudioFrame] = []

        frame_size = AudioConstants.BYTES_PER_SAMPLE
        while len(session.pending_bytes) >= frame_size:
            frame_data = session.pending_bytes[:frame_size]
            session.pending_bytes = session.pending_bytes[frame_size:]
            session.total_frames += 1
            session.total_pcm_bytes += frame_size
            frames.append(AudioFrame(index=session.total_frames, data=frame_data))

        return frames

    def _wav_to_pcm(self, wav_bytes: bytes) -> bytes:
        if len(wav_bytes) < 44:
            raise ValueError("WAV data too short")

        if wav_bytes[0:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
            raise ValueError("Invalid WAV header")

        fmt_index = wav_bytes.find(b"fmt ")
        if fmt_index == -1:
            raise ValueError("Missing fmt chunk")

        fmt_size = int.from_bytes(wav_bytes[fmt_index + 4:fmt_index + 8], "little")
        fmt_start = fmt_index + 8
        audio_format = int.from_bytes(wav_bytes[fmt_start:fmt_start + 2], "little")
        channels = int.from_bytes(wav_bytes[fmt_start + 2:fmt_start + 4], "little")
        sample_rate = int.from_bytes(wav_bytes[fmt_start + 4:fmt_start + 8], "little")
        bits_per_sample = int.from_bytes(wav_bytes[fmt_start + 14:fmt_start + 16], "little")

        if audio_format != 1:
            raise ValueError("WAV must be PCM")
        if channels != AudioConstants.CHANNELS:
            raise ValueError("WAV must be mono")
        if sample_rate != AudioConstants.SAMPLE_RATE:
            raise ValueError("WAV must be 16 kHz")
        if bits_per_sample != AudioConstants.BITS_PER_SAMPLE:
            raise ValueError("WAV must be 16-bit")

        data_index = wav_bytes.find(b"data")
        if data_index == -1:
            raise ValueError("Missing data chunk")

        data_size = int.from_bytes(wav_bytes[data_index + 4:data_index + 8], "little")
        data_start = data_index + 8
        data_end = data_start + data_size

        if len(wav_bytes) < data_end:
            raise ValueError("WAV data truncated")

        return wav_bytes[data_start:data_end]
    
    def _load_verify_audio_bytes(self) -> None:
        self.verify_audio_bytes = self._load_audio_bytes("./app/assets/verify_audio.wav")

    def _load_pink_audio_bytes(self) -> None:
        self.pink_audio_bytes = self._load_audio_bytes("./app/assets/pinknose16khz.wav")

    def _load_audio_bytes(self, file_path: str) -> bytes:
        with open(file_path, "rb") as f:
            wav_bytes = f.read()
            return self._wav_to_pcm(wav_bytes)

    def _new_session_id(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
