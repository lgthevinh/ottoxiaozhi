from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.core.config as _config_mod
_config_mod.get_settings.cache_clear()

from app.services.assistant import llm_client


async def main() -> None:
    messages = [{"role": "user", "content": "Xin chào, bạn là ai? Rất vui được gặp bạn."}]
    print("Calling LLM...")
    async for token in llm_client.respond(messages):
        print(repr(token), end="", flush=True)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
