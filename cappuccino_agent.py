import asyncio

import json

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from tool_manager import ToolManager
from state_manager import AgentStateManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class CappuccinoAgent:
    """Asynchronous agent orchestrating LLM interactions and tool use."""

    def __init__(
        self,
        api_key: str | None = None,
        db_path: str | None = None,
        *,
        llm: Optional[Any] = None,
        tool_manager: Optional[ToolManager] = None,
    ) -> None:
        """Initialize the agent with optional custom LLM and ToolManager."""
        self.llm = llm
        self.client = None if llm else AsyncOpenAI(api_key=api_key) if api_key else None
        self.tool_manager = tool_manager or ToolManager(db_path or "agent_state.db")
        self.messages: List[Dict[str, Any]] = []
        self.task_plan: List[Dict[str, Any]] = []
        self.current_phase_id = 0
        self.executor = ThreadPoolExecutor()
        self.state_manager = AgentStateManager(db_path or "agent_state.db")
        self._initialize_system_prompt()

    @classmethod
    async def create(
        cls,
        db_path: str,
        api_key: str | None = None,
        *,
        llm: Optional[Any] = None,
        tool_manager: Optional[ToolManager] = None,
    ) -> "CappuccinoAgent":
        """Instantiate agent and load state from the given database."""
        self = cls(api_key=api_key, db_path=db_path, llm=llm, tool_manager=tool_manager)
        data = await self.state_manager.load()
        self.task_plan = data.get("task_plan", [])
        self.messages = data.get("history", self.messages)
        self.current_phase_id = data.get("phase", 0)
        return self

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

    async def set_task_plan(self, plan: List[Dict[str, Any]]) -> None:
        self.task_plan = plan
        await self.state_manager.save(self.task_plan, self.messages, self.current_phase_id)

    async def add_message(self, role: str, content: str) -> None:
        await self._add_message(role, content)
        await self.state_manager.save(self.task_plan, self.messages, self.current_phase_id)

    async def advance_phase(self) -> None:
        self.current_phase_id += 1
        await self.state_manager.save(self.task_plan, self.messages, self.current_phase_id)

    @property
    def history(self) -> List[Dict[str, Any]]:
        return self.messages

    @property
    def phase(self) -> int:
        return self.current_phase_id

    async def get_cached_result(self, key: str) -> Optional[str]:
        """Delegate to ToolManager cache retrieval."""
        return await self.tool_manager.get_cached_result(key)

    async def set_cached_result(self, key: str, value: str) -> None:
        """Delegate to ToolManager cache storage."""
        await self.tool_manager.set_cached_result(key, value)

    async def call_llm(self, prompt: str) -> str:
        """Call the LLM or fallback stub and cache the result."""
        cache_key = f"llm:{prompt}"
        cached = await self.get_cached_result(cache_key)
        if cached is not None:
            return cached

        if self.llm:
            resp = await self.llm(prompt)
            result = resp if isinstance(resp, str) else resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        elif self.client:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.choices[0].message.content or ""
        else:
            result = prompt[::-1]

        await self.set_cached_result(cache_key, result)
        return result

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
                if self.llm:
                    response = await self.llm(self.messages)
                else:
                    response = await self.client.chat.completions.create(
                        model="gpt-4o",
                        messages=self.messages,
                        tools=tools_schema or [],
                        tool_choice="auto",
                    )
                if isinstance(response, dict):
                    response_message = response["choices"][0]["message"]
                else:
                    response_message = response.choices[0].message
                role = getattr(response_message, "role", None) or response_message.get("role", "assistant")
                content = getattr(response_message, "content", None) or response_message.get("content", "")
                tool_calls = getattr(response_message, "tool_calls", None) or response_message.get("tool_calls")
                await self._add_message(
                    role,
                    content,
                    tool_calls,
                )

                if tool_calls:
                    tool_outputs = []
                    for tool_call in tool_calls:
                        if isinstance(tool_call, dict):
                            function_name = tool_call["function"]["name"]
                            function_args = json.loads(tool_call["function"]["arguments"])
                            call_id = tool_call.get("id", "")
                        else:
                            function_name = tool_call.function.name
                            function_args = json.loads(tool_call.function.arguments)
                            call_id = tool_call.id
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
                                "tool_call_id": call_id,
                                "output": tool_output,
                            })
                        else:
                            error_message = f"Error: Tool '{function_name}' not found in ToolManager."
                            logging.error(error_message)
                            tool_outputs.append({
                                "tool_call_id": call_id,
                                "output": {"error": error_message},
                            })

                    for output_entry in tool_outputs:
                        await self._add_message(
                            "tool",
                            json.dumps(output_entry["output"]),
                            tool_call_id=output_entry["tool_call_id"],
                        )
                    return [entry["output"] for entry in tool_outputs]

                elif content:
                    print(f"Cappuccino: {content}")
                    if "タスクが完了しました" in content or "終了します" in content:
                        logging.info("Task likely completed. Ending agent loop.")
                        return content
                    return content

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

    async def close(self) -> None:
        """Explicitly close underlying resources."""
        if hasattr(self.tool_manager, "close"):
            close_fn = getattr(self.tool_manager, "close")
            if asyncio.iscoroutinefunction(close_fn):
                await close_fn()
            else:
                close_fn()
        await self.state_manager.close()
