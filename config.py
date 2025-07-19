import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    """Application configuration loaded from environment variables."""

    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3")
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    fractal_depth: int = int(os.getenv("FRACTAL_DEPTH", "2"))
    fractal_breadth: int = int(os.getenv("FRACTAL_BREADTH", "3"))


settings = Settings()
