import asyncio
import json

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from tool_manager import ToolManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class CappuccinoAgent:
    """Asynchronous agent orchestrating LLM interactions and tool use."""

    def __init__(self, api_key: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.tool_manager = ToolManager()
        self.messages: List[Dict[str, Any]] = []
        self.task_plan: List[Dict[str, Any]] = []
        self.current_phase_id = 0
        self.executor = ThreadPoolExecutor()
        self._initialize_system_prompt()

    def _initialize_system_prompt(self) -> None:
        """Add initial system prompt describing the agent."""
        system_prompt = (
            "あなたはCappuccinoという名前の、ユーザーの多様な要求に応えることができる汎用AIアシスタントです。\n"
            "ユーザーの指示を理解し、適切なツールを自律的に選択・実行することで、複雑なタスクを効率的に解決してください。\n"
            "利用可能なツールは以下の通りです。これらのツールを適切に利用してタスクを遂行してください。\n"
            "思考プロセスは日本語で行い、ユーザーへの応答も日本語で行ってください。\n"
            "タスクが完了したら、`agent_end_task`ツールを呼び出して終了してください。\n"
            "不明な点があれば、ユーザーに質問してください。"
        )
        self.messages.append({"role": "system", "content": system_prompt})

    async def _add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ) -> None:
        """Append a message and persist it to the database."""
        message: Dict[str, Any] = {"role": role, "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        if tool_call_id:
            message["tool_call_id"] = tool_call_id
        self.messages.append(message)
        logging.info(f"Added message: {message}")

        conn = await self.tool_manager._get_db_connection()
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT)"
        )
        await conn.execute(
            "INSERT INTO history (role, content) VALUES (?, ?)",
            (role, content),
        )
        await conn.commit()

    async def run(self, user_query: str, tools_schema: Optional[List[Dict[str, Any]]] = None) -> None:
        """Main asynchronous loop processing user input and invoking tools."""
        await self._add_message("user", user_query)

        while True:
            logging.info("Entering async agent loop...")
            try:
                response = await self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=self.messages,
                    tools=tools_schema or [],
                    tool_choice="auto",
                )
                response_message = response.choices[0].message
                await self._add_message(
                    response_message.role,
                    response_message.content or "",
                    response_message.tool_calls,
                )

                if response_message.tool_calls:
                    tool_outputs = []
                    for tool_call in response_message.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        logging.info(
                            f"LLM requested tool call: {function_name} with args {function_args}"
                        )
                        if hasattr(self.tool_manager, function_name):
                            tool_function = getattr(self.tool_manager, function_name)
                            if asyncio.iscoroutinefunction(tool_function):
                                tool_output = await tool_function(**function_args)
                            else:
                                loop = asyncio.get_running_loop()
                                tool_output = await loop.run_in_executor(
                                    self.executor, tool_function, **function_args
                                )
                            logging.info(
                                f"Tool {function_name} executed, output: {tool_output}"
                            )
                            tool_outputs.append({
                                "tool_call_id": tool_call.id,
                                "output": tool_output,
                            })
                        else:
                            error_message = f"Error: Tool '{function_name}' not found in ToolManager."
                            logging.error(error_message)
                            tool_outputs.append({
                                "tool_call_id": tool_call.id,
                                "output": {"error": error_message},
                            })

                    for output_entry in tool_outputs:
                        await self._add_message(
                            "tool",
                            json.dumps(output_entry["output"]),
                            tool_call_id=output_entry["tool_call_id"],
                        )
                    continue

                elif response_message.content:
                    print(f"Cappuccino: {response_message.content}")
                    if "タスクが完了しました" in response_message.content or "終了します" in response_message.content:
                        logging.info("Task likely completed. Ending agent loop.")
                        break
                    break

            except Exception as e:  # pragma: no cover - error paths not deterministic
                logging.error(f"An error occurred in the agent loop: {e}")
                await self._add_message("system", f"エージェントループでエラーが発生しました: {e}")
                break

        if hasattr(self.tool_manager, "close"):
            close_fn = getattr(self.tool_manager, "close")
            if asyncio.iscoroutinefunction(close_fn):
                await close_fn()
            else:
                close_fn()
