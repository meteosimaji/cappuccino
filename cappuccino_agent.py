import json
import logging
from typing import List, Dict, Optional

from openai import OpenAI

from tool_manager import ToolManager
from config import settings


class CappuccinoAgent:
    """Simple agent that communicates with OpenAI's API using ToolManager."""

    def __init__(self, api_key: Optional[str] = None):
        self.client = OpenAI(api_key=api_key or settings.openai_api_key)
        self.tool_manager = ToolManager()
        self.messages: List[Dict[str, str]] = []
        self._initialize_system_prompt()

    def _initialize_system_prompt(self) -> None:
        prompt = (
            "You are Cappuccino, a helpful AI assistant. "
            "Respond in Japanese."
        )
        self.messages.append({"role": "system", "content": prompt})

    def _add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        logging.info("Added message: %s", content)

    def run(self, user_query: str) -> str:
        """Send the query to OpenAI and return the response text."""
        self._add_message("user", user_query)
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=self.messages,
        )
        message = response.choices[0].message
        self._add_message(message.role, message.content or "")
        return message.content or ""
