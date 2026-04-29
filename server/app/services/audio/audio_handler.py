from __future__ import annotations

import struct
from pathlib import Path
from typing import Iterator

from app.services.audio.audio_config import AudioConstants

_ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"
_assets: dict[str, bytes] = {}


def _wav_to_pcm(wav_bytes: bytes) -> bytes:
    if len(wav_bytes) < 44:
        raise ValueError("WAV data too short")
    if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise ValueError("Invalid WAV header")

    fmt_index = wav_bytes.find(b"fmt ")
    if fmt_index == -1:
        raise ValueError("Missing fmt chunk")

    fmt_start = fmt_index + 8
    audio_format, channels, sample_rate = struct.unpack_from("<HHI", wav_bytes, fmt_start)
    bits_per_sample = struct.unpack_from("<H", wav_bytes, fmt_start + 14)[0]

    if audio_format != 1:
        raise ValueError("WAV must be PCM (format 1)")
    if channels != AudioConstants.CHANNELS:
        raise ValueError(f"WAV must be mono, got {channels} channels")
    if sample_rate != AudioConstants.SAMPLE_RATE:
        raise ValueError(f"WAV must be {AudioConstants.SAMPLE_RATE} Hz, got {sample_rate}")
    if bits_per_sample != AudioConstants.BITS_PER_SAMPLE:
        raise ValueError(f"WAV must be {AudioConstants.BITS_PER_SAMPLE}-bit, got {bits_per_sample}")

    data_index = wav_bytes.find(b"data")
    if data_index == -1:
        raise ValueError("Missing data chunk")

    data_size = struct.unpack_from("<I", wav_bytes, data_index + 4)[0]
    data_start = data_index + 8
    data_end = data_start + data_size

    if len(wav_bytes) < data_end:
        raise ValueError("WAV data truncated")

    return wav_bytes[data_start:data_end]


def _load_asset(filename: str) -> bytes:
    return _wav_to_pcm((_ASSETS_DIR / filename).read_bytes())


def load_assets() -> None:
    _assets["verify"] = _load_asset("verify_audio.wav")
    _assets["pink"] = _load_asset("pinknose16khz.wav")


def frame_pcm(pcm: bytes) -> bytes:
    return bytes([AudioConstants.PACKET_START]) + pcm + bytes([AudioConstants.PACKET_END])


def unframe(data: bytes) -> bytes | None:
    if len(data) < 3:
        return None
    if data[0] != AudioConstants.PACKET_START or data[-1] != AudioConstants.PACKET_END:
        return None
    return data[1:-1]


def get_asset(name: str) -> bytes:
    return _assets[name]


def iter_asset_frames(name: str) -> Iterator[bytes]:
    pcm = _assets[name]
    frame_size = AudioConstants.BYTES_PER_SAMPLE
    offset = 0
    while offset < len(pcm):
        yield frame_pcm(pcm[offset:offset + frame_size])
        offset += frame_size


load_assets()
