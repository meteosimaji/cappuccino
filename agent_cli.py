import sys
import asyncio
import base64
import io
import os
from dotenv import load_dotenv
from ollama_client import OllamaLLM
from PIL import Image

load_dotenv()
client = OllamaLLM(os.getenv("OLLAMA_MODEL", "llama3"))


async def call_llm(prompt: str) -> dict[str, list[str]]:
    """Send a prompt directly to the local LLM."""
    text = await client(prompt)
    return {"text": text, "images": []}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    query = sys.argv[1] if len(sys.argv) > 1 else input("Query: ")
    result = asyncio.run(call_llm(query))

    text_output = result.get("text", "")
    if text_output:
        print(text_output)

    images = result.get("images", [])
    if images:
        for i, img_data_uri in enumerate(images):
            try:
                _, encoded = img_data_uri.split(",", 1)
                binary_data = base64.b64decode(encoded)
                image = Image.open(io.BytesIO(binary_data))
                filename = f"generated_image_{i+1}.png"
                image.save(filename)
                print(f"画像{i+1}: {filename} に保存しました。")
            except Exception as e:  # pragma: no cover - manual use
                print(f"画像{i+1}の保存中にエラーが発生しました: {e}")


if __name__ == "__main__":  # pragma: no cover - manual run
    main()
