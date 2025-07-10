import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

from tool_manager import ToolManager


class CappuccinoAgent:
    """Minimal asynchronous agent using a ToolManager and pluggable LLM."""

    def __init__(self, llm: Callable[[List[Dict[str, Any]]], Any], tool_manager: Optional[ToolManager] = None):
        self.llm = llm
        self.tool_manager = tool_manager or ToolManager()
        self.messages: List[Dict[str, Any]] = []

    async def run(self, query: str) -> Any:
        """Run the agent with a user query and return the final response."""
        self.messages.append({"role": "user", "content": query})
        response = await self.llm(self.messages)
        message = response["choices"][0]["message"]

        if message.get("tool_calls"):
            outputs = []
            for call in message["tool_calls"]:
                func_name = call["function"]["name"]
                args = json.loads(call["function"].get("arguments", "{}"))
                if hasattr(self.tool_manager, func_name):
                    func = getattr(self.tool_manager, func_name)
                    if asyncio.iscoroutinefunction(func):
                        result = await func(**args)
                    else:
                        loop = asyncio.get_running_loop()
                        result = await loop.run_in_executor(None, func, **args)
                else:
                    result = {"error": f"Tool '{func_name}' not found"}
                outputs.append(result)
            return outputs
        return message.get("content")
