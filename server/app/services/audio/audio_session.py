from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AudioSession:
    session_id: str
    created_at: datetime
    total_frames: int = 0
    total_pcm_bytes: int = 0
    pending_bytes: bytes = field(default_factory=bytes)
    packet_open: bool = False
    packet_buffer: bytearray = field(default_factory=bytearray)
