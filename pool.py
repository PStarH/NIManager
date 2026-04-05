import asyncio
import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)

class KeyStatus(Enum):
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"

@dataclass
class KeyMetrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    last_used: Optional[float] = None
    last_failure: Optional[float] = None
    avg_latency_ms: float = 0.0

@dataclass
class APIKey:
    key: str
    name: str = ""
    status: KeyStatus = KeyStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    timestamps: deque = field(default_factory=deque)
    metrics: KeyMetrics = field(default_factory=KeyMetrics)
    
    def __post_init__(self):
        if not self.name:
            self.name = f"key_{self.key[:8]}"
        object.__setattr__(self, 'timestamps', deque())

class KeyPool:
    def __init__(self, rpm_limit: int = 40, window_seconds: int = 60, max_consecutive_failures: int = 3):
        self.rpm_limit = rpm_limit
        self.window_seconds = window_seconds
        self.max_consecutive_failures = max_consecutive_failures
        self._keys: dict[str, APIKey] = {}
        self._lock = asyncio.Lock()
        self._key_order: list[str] = []
        self._current_idx: int = 0
        
    async def add_key(self, key: str, name: str = "") -> APIKey:
        async with self._lock:
            if key in self._keys:
                raise ValueError(f"Key {key[:8]}... already exists")
            api_key = APIKey(key=key, name=name)
            self._keys[key] = api_key
            self._key_order.append(key)
            logger.info(f"Added API key: {api_key.name}")
            return api_key
    
    async def remove_key(self, key: str) -> bool:
        async with self._lock:
            if key not in self._keys:
                return False
            del self._keys[key]
            self._key_order.remove(key)
            if self._current_idx >= len(self._key_order):
                self._current_idx = 0
            logger.info(f"Removed API key: {key[:8]}...")
            return True
    
    async def disable_key(self, key: str):
        async with self._lock:
            if key in self._keys:
                self._keys[key].status = KeyStatus.DISABLED
                logger.warning(f"Disabled key: {key[:8]}...")
    
    async def enable_key(self, key: str):
        async with self._lock:
            if key in self._keys:
                self._keys[key].status = KeyStatus.ACTIVE
                self._keys[key].metrics.consecutive_failures = 0
                logger.info(f"Enabled key: {key[:8]}...")
    
    def _clean_old_timestamps(self, key: APIKey, now: float):
        while key.timestamps and now - key.timestamps[0] > self.window_seconds:
            key.timestamps.popleft()
    
    async def get_available_key(self, timeout: float = 60.0) -> Optional[APIKey]:
        deadline = time.monotonic() + timeout
        
        while time.monotonic() < deadline:
            async with self._lock:
                now = time.monotonic()
                
                # 尝试恢复限流的key
                for key in self._keys.values():
                    if key.status == KeyStatus.RATE_LIMITED:
                        self._clean_old_timestamps(key, now)
                        if len(key.timestamps) < self.rpm_limit:
                            key.status = KeyStatus.ACTIVE
                            logger.info(f"Key {key.name} recovered from rate limit")
                
                # 轮询选择可用key
                if not self._key_order:
                    await asyncio.sleep(0.1)
                    continue
                
                for _ in range(len(self._key_order)):
                    key_str = self._key_order[self._current_idx]
                    self._current_idx = (self._current_idx + 1) % len(self._key_order)
                    
                    key = self._keys[key_str]
                    if key.status != KeyStatus.ACTIVE:
                        continue
                    
                    self._clean_old_timestamps(key, now)
                    if len(key.timestamps) < self.rpm_limit:
                        key.timestamps.append(now)
                        key.metrics.last_used = now
                        return key
            
            await asyncio.sleep(0.05)
        
        return None
    
    async def report_success(self, key: str, latency_ms: float):
        async with self._lock:
            if key not in self._keys:
                return
            k = self._keys[key]
            k.metrics.total_requests += 1
            k.metrics.successful_requests += 1
            k.metrics.consecutive_failures = 0
            k.metrics.avg_latency_ms = k.metrics.avg_latency_ms * 0.9 + latency_ms * 0.1
    
    async def report_failure(self, key: str, is_rate_limit: bool = False):
        async with self._lock:
            if key not in self._keys:
                return
            k = self._keys[key]
            k.metrics.total_requests += 1
            k.metrics.failed_requests += 1
            k.metrics.consecutive_failures += 1
            k.metrics.last_failure = time.time()
            if is_rate_limit:
                k.status = KeyStatus.RATE_LIMITED
                logger.warning(f"Key {k.name} rate limited")
            elif k.metrics.consecutive_failures >= self.max_consecutive_failures:
                k.status = KeyStatus.UNHEALTHY
                logger.error(f"Key {k.name} marked unhealthy")
    
    async def get_status(self) -> dict:
        async with self._lock:
            return {
                "total_keys": len(self._keys),
                "active_keys": sum(1 for k in self._keys.values() if k.status == KeyStatus.ACTIVE),
                "keys": [
                    {
                        "name": k.name,
                        "key_preview": k.key[:8] + "...",
                        "status": k.status.value,
                        "current_rpm": len(k.timestamps),
                        "metrics": {
                            "total_requests": k.metrics.total_requests,
                            "success_rate": k.metrics.successful_requests / max(1, k.metrics.total_requests) * 100,
                            "avg_latency_ms": round(k.metrics.avg_latency_ms, 2),
                            "consecutive_failures": k.metrics.consecutive_failures
                        }
                    }
                    for k in self._keys.values()
                ]
            }
