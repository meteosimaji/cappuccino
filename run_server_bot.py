import asyncio
import uvicorn

from api import app
from discordbot.bot import start_bot
from logging_config import setup_logging

async def start_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info", log_config=None)
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    setup_logging("bot.log")
    await asyncio.gather(start_server(), start_bot())

if __name__ == "__main__":
    asyncio.run(main())
