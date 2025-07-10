import json
from typing import Any, Dict, Optional

from tool_manager import ToolManager

class CappuccinoAgent:
    """Simplified agent demonstrating cache integration."""

    def __init__(self, tool_manager: Optional[ToolManager] = None):
        self.tool_manager = tool_manager or ToolManager()
        self.messages: list[Dict[str, Any]] = []

    async def get_cached_result(self, key: str) -> Optional[str]:
        return await self.tool_manager.get_cached_result(key)

    async def set_cached_result(self, key: str, value: str) -> None:
        await self.tool_manager.set_cached_result(key, value)

    async def call_llm(self, prompt: str) -> str:
        """Example LLM call with caching. Actual LLM integration omitted."""
        cache_key = f"llm:{prompt}"
        cached = await self.get_cached_result(cache_key)
        if cached:
            return cached
        # Placeholder LLM response
        response = prompt[::-1]
        await self.set_cached_result(cache_key, response)
        self.messages.append({"role": "user", "content": prompt})
        self.messages.append({"role": "assistant", "content": response})
        return response
