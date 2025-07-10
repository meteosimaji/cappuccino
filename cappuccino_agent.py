"""Asynchronous CappuccinoAgent using a thread pool for LLM calls."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore


class CappuccinoAgent:
    """Minimal agent wrapper around the OpenAI client.

    The OpenAI Python client performs network requests synchronously. To run
    multiple prompts concurrently, we wrap those synchronous calls in a
    ``ThreadPoolExecutor`` and schedule them with ``asyncio``.  This allows
    ``asyncio.gather`` to issue several requests in parallel without blocking
    the event loop.
    """

    def __init__(self, api_key: str, max_workers: int = 4) -> None:
        if OpenAI is None:
            raise ImportError("openai package is required to use CappuccinoAgent")
        self.client = OpenAI(api_key=api_key)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def _call_llm_sync(self, messages: List[Dict[str, str]]) -> str:
        """Synchronous wrapper around ``chat.completions.create``."""
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
        )
        return response.choices[0].message.content or ""

    async def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Execute a single LLM call in the thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self._call_llm_sync, messages)

    async def run_parallel_prompts(self, prompts: List[str]) -> List[str]:
        """Run multiple prompts in parallel using the thread pool."""
        tasks = [
            self._call_llm([{"role": "user", "content": prompt}]) for prompt in prompts
        ]
        return await asyncio.gather(*tasks)

    def close(self) -> None:
        """Shutdown the internal executor."""
        self.executor.shutdown(wait=True)
