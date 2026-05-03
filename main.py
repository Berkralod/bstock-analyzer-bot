import asyncio
import json
import logging

from fastapi import FastAPI, Request, Response, HTTPException
from telegram import Update
from contextlib import asynccontextmanager

import config
from bot.telegram_handler import build_application
from utils.cache import Cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_tg_app = build_application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _tg_app.initialize()
    logger.info("Telegram app initialized.")
    yield
    await _tg_app.shutdown()
    await Cache.close()
    logger.info("Shutdown complete.")


app = FastAPI(title="B-Stock Analyzer Bot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != config.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    body = await request.body()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Bad JSON")

    update = Update.de_json(data, _tg_app.bot)
    # Process in background so HTTP 200 returns immediately to Telegram
    asyncio.create_task(_tg_app.process_update(update))
    return Response(status_code=200)
