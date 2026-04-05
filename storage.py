import asyncio
import aiosqlite
import json
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class KeyStorage:
    """持久化存储"""
    
    def __init__(self, db_path: str = "./nim_pool.db"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
    
    async def init(self):
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key TEXT PRIMARY KEY,
                name TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                metrics TEXT DEFAULT '{}'
            )
        """)
        await self._db.commit()
        logger.info(f"Database initialized: {self.db_path}")
    
    async def close(self):
        if self._db:
            await self._db.close()
    
    async def save_key(self, key: str, name: str = "", status: str = "active"):
        await self._db.execute(
            "INSERT OR REPLACE INTO api_keys (key, name, status, created_at) VALUES (?, ?, ?, ?)",
            (key, name, status, datetime.utcnow().isoformat())
        )
        await self._db.commit()
    
    async def update_status(self, key: str, status: str):
        await self._db.execute(
            "UPDATE api_keys SET status = ? WHERE key = ?",
            (status, key)
        )
        await self._db.commit()
    
    async def delete_key(self, key: str):
        await self._db.execute("DELETE FROM api_keys WHERE key = ?", (key,))
        await self._db.commit()
    
    async def load_all_keys(self) -> list[dict]:
        async with self._db.execute(
            "SELECT key, name, status FROM api_keys"
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"key": r[0], "name": r[1], "status": r[2]} for r in rows]
