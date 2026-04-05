import asyncio
import logging
import httpx
from datetime import datetime
from typing import Optional

from pool import KeyPool, KeyStatus

logger = logging.getLogger(__name__)

class HealthChecker:
    """后台健康检查器"""
    
    def __init__(self, pool: KeyPool, base_url: str, interval: int = 300):
        self.pool = pool
        self.base_url = base_url.rstrip("/")
        self.interval = interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Health checker started")
    
    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Health checker stopped")
    
    async def _check_loop(self):
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                await self._check_all_keys()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
    
    async def _check_all_keys(self):
        """检查所有非活跃Key是否恢复"""
        async with self.pool._lock:
            keys_to_check = [
                k for k in self.pool._keys.values() 
                if k.status in (KeyStatus.UNHEALTHY, KeyStatus.RATE_LIMITED)
            ]
        
        if not keys_to_check:
            return
        
        logger.info(f"Health checking {len(keys_to_check)} keys")
        
        for key in keys_to_check:
            try:
                healthy = await self._probe_key(key.key)
                if healthy:
                    async with self.pool._lock:
                        if key.key in self.pool._keys:
                            self.pool._keys[key.key].status = KeyStatus.ACTIVE
                            self.pool._keys[key.key].metrics.consecutive_failures = 0
                            logger.info(f"Key {key.name} recovered")
            except Exception as e:
                logger.debug(f"Key {key.name} still unhealthy: {e}")
    
    async def _probe_key(self, key: str) -> bool:
        """探测单个Key是否可用"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {key}"}
                )
                return resp.status_code < 500
        except Exception:
            return False
