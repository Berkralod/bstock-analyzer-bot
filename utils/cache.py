import json
import hashlib
import redis.asyncio as aioredis
from typing import Any, Optional
import config


class Cache:
    _client: Optional[aioredis.Redis] = None

    @classmethod
    async def get_client(cls) -> aioredis.Redis:
        if cls._client is None:
            cls._client = aioredis.from_url(config.REDIS_URL, decode_responses=True)
        return cls._client

    @classmethod
    def _key(cls, namespace: str, data: str) -> str:
        h = hashlib.md5(data.encode()).hexdigest()
        return f"bstock:{namespace}:{h}"

    @classmethod
    async def get(cls, namespace: str, query: str) -> Optional[Any]:
        client = await cls.get_client()
        key = cls._key(namespace, query)
        raw = await client.get(key)
        if raw:
            return json.loads(raw)
        return None

    @classmethod
    async def set(cls, namespace: str, query: str, value: Any, ttl: int) -> None:
        client = await cls.get_client()
        key = cls._key(namespace, query)
        await client.setex(key, ttl, json.dumps(value))

    @classmethod
    async def get_history(cls, limit: int = 10) -> list:
        client = await cls.get_client()
        keys = await client.lrange("bstock:history", 0, limit - 1)
        results = []
        for raw in keys:
            try:
                results.append(json.loads(raw))
            except Exception:
                pass
        return results

    @classmethod
    async def push_history(cls, entry: dict) -> None:
        client = await cls.get_client()
        await client.lpush("bstock:history", json.dumps(entry))
        await client.ltrim("bstock:history", 0, 49)

    @classmethod
    async def close(cls) -> None:
        if cls._client:
            await cls._client.aclose()
            cls._client = None
