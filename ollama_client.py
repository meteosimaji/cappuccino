from __future__ import annotations

from typing import Any, Dict, List, Optional

from ollama import AsyncClient


class OllamaLLM:
    """Wrapper mimicking the OpenAI client interface using Ollama."""

    def __init__(self, model: str, host: str | None = None) -> None:
        self.client = AsyncClient(host=host)
        self.model = model
        self.chat = self._Chat(self)

    class _Chat:
        def __init__(self, outer: "OllamaLLM") -> None:
            self.outer = outer
            self.completions = self._Completions(outer)

        class _Completions:
            def __init__(self, outer: "OllamaLLM") -> None:
                self.outer = outer

            async def create(
                self,
                model: str,
                messages: List[Dict[str, str]],
                temperature: float = 0,
            ) -> Any:
                resp = await self.outer.client.chat(model=model, messages=messages)

                class Msg:
                    def __init__(self, content: str) -> None:
                        self.content = content

                class Choice:
                    def __init__(self, message: Msg) -> None:
                        self.message = message

                return type(
                    "Resp",
                    (),
                    {
                        "choices": [Choice(Msg(resp.message["content"]))],
                    },
                )()

    async def __call__(self, prompt: str) -> str:
        resp = await self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.message["content"]

