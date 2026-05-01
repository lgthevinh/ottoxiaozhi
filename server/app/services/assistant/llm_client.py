from __future__ import annotations

from typing import AsyncIterator

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.assistant.config import LLM_MODEL, LLM_BASE_URL, SYSTEM_PROMPT


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=get_settings().llm_api_key,
        base_url=LLM_BASE_URL,
    )


async def respond(
    messages: list[dict],
    system_prompt: str = SYSTEM_PROMPT,
) -> AsyncIterator[str]:
    full_messages = [{"role": "system", "content": system_prompt}, *messages]

    stream = await _client().chat.completions.create(
        model=LLM_MODEL,
        messages=full_messages,
        stream=True,
    )

    async for chunk in stream:
        token = chunk.choices[0].delta.content
        if token:
            yield token
