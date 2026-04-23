import os

import sys

from websockets.sync.client import connect

PACKET_START = 0x01
PACKET_END = 0x03

def test_audio_websocket_accepts_pcm_packet() -> None:
    base_url = os.getenv("AUDIO_WS_BASE_URL", "wss://thingedges-neo-1.tail47f64f.ts.net")
    packet = "pink"

    with connect(f"{base_url}/ws/audio/pink/test_device") as websocket:
        websocket.send(packet)
        try:
            message = websocket.recv()
            print(message)
        except TimeoutError:
            print("No websocket response within 1s")


def main() -> None:
    try:
        test_audio_websocket_accepts_pcm_packet()
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
