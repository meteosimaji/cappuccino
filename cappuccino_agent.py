import asyncio

import json

import logging
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Any, Dict, List, Optional, AsyncGenerator

from openai import AsyncOpenAI

from tool_manager import ToolManager
from state_manager import StateManager
from self_improver import SelfImprover
from agents import PlannerAgent, ExecutorAgent, AnalyzerAgent


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class CappuccinoAgent:
    """Asynchronous agent orchestrating LLM interactions and tool use."""

    def __init__(
        self,
        api_key: str | None = None,
        db_path: str | None = None,

        tool_manager: Optional[ToolManager] = None,
        llm: Optional[Any] = None,
        *,
        thread_workers: Optional[int] = None,
        process_workers: Optional[int] = None,
    ) -> None:
        self.client = AsyncOpenAI(api_key=api_key) if api_key and llm is None else None
        self.llm = llm
        self.api_key = api_key

        self.tool_manager = tool_manager or ToolManager(db_path or "agent_state.db")
        self.planner_agent = PlannerAgent()
        self.executor_agent = ExecutorAgent(self.tool_manager, llm)
        self.analyzer_agent = AnalyzerAgent()
        self.messages: List[Dict[str, Any]] = []
        self.task_plan: List[Dict[str, Any]] = []
        self.current_phase_id = 0
        self.thread_executor = (
            ThreadPoolExecutor(max_workers=thread_workers)
            if thread_workers is not None
            else ThreadPoolExecutor()
        )
        self.process_executor = (
            ProcessPoolExecutor(max_workers=process_workers)
            if process_workers is not None
            else None
        )
        self.state_manager = StateManager(db_path or "agent_state.db")
        self.self_improver = SelfImprover(self.state_manager, self.tool_manager, api_key)
        self._initialize_system_prompt()

    @classmethod
    async def create(
        cls,
        db_path: str,
        api_key: str | None = None,
        *,
        llm: Optional[Any] = None,
        tool_manager: Optional[ToolManager] = None,
        thread_workers: Optional[int] = None,
        process_workers: Optional[int] = None,
    ) -> "CappuccinoAgent":
        """Instantiate agent and load state from the given database."""
        self = cls(
            api_key=api_key,
            db_path=db_path,
            llm=llm,
            tool_manager=tool_manager,
            thread_workers=thread_workers,
            process_workers=process_workers,
        )
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
        if self.self_improver:
            try:
                await self.self_improver.improve()
            except Exception as exc:  # pragma: no cover - best effort
                logging.error(f"SelfImprover failed: {exc}")

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

    async def _run_sync(self, func, *args, cpu_bound: bool = False, **kwargs):
        """Run blocking function in the configured executor."""
        loop = asyncio.get_running_loop()
        executor = (
            self.process_executor if cpu_bound and self.process_executor else self.thread_executor
        )
        return await loop.run_in_executor(executor, lambda: func(*args, **kwargs))

    async def call_llm(self, prompt: str) -> str:
        """Call the LLM with emotion context and cache the result."""
        cache_key = f"llm:{prompt}"
        cached = await self.get_cached_result(cache_key)
        if cached is not None:
            return cached

        from emotion_recognizer import detect_emotion

        emotion = detect_emotion(prompt)
        prompt_with_emotion = f"{prompt}\n[User sentiment: {emotion}]"

        if self.llm:
            resp = await self.llm(prompt_with_emotion)
            result = (
                resp
                if isinstance(resp, str)
                else resp.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
        elif self.client:
            response = await self.client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt_with_emotion}],
            )
            result = response.choices[0].message.content or ""
        else:
            # Fallback stub preserves original behaviour for tests
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

    async def run(
        self, user_query: str, tools_schema: Optional[List[Dict[str, Any]]] = None
    ) -> Any:
        """Run the planner, executor and analyzer pipeline."""

        plan_queue: asyncio.Queue = asyncio.Queue()
        result_queue: asyncio.Queue = asyncio.Queue()

        planner_task = asyncio.create_task(self.planner_agent.plan(user_query, plan_queue))
        executor_task = asyncio.create_task(self.executor_agent.execute(plan_queue, result_queue))

        await planner_task
        await executor_task
        results = await self.analyzer_agent.analyze(result_queue)
        return results


    async def close(self) -> None:
        """Close associated resources."""
        if hasattr(self.tool_manager, "close"):
            fn = getattr(self.tool_manager, "close")
            if asyncio.iscoroutinefunction(fn):
                await fn()
            else:
                fn()

        await self.state_manager.close()
        self.thread_executor.shutdown(wait=False)
        if self.process_executor:
            self.process_executor.shutdown(wait=False)
